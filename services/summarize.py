"""회의 스크립트를 구조화된 요약(JSON)으로 변환하는 서비스.

Claude(Anthropic API)를 사용한다. 파이프라인 전체에서 "두뇌" 역할을 담당하며,
STT(services/stt.py)가 만든 텍스트를 읽고 회의록에 바로 쓸 수 있는 형태
(회의명/참석자/안건/논의내용/결정사항/액션아이템)로 정리한다.
"""

import json
import re

import anthropic

# 오류 안내 문구를 여러 줄로 조립할 때 사용하는 개행 문자.
NL = chr(10)

# Claude에게 보낼 프롬프트 템플릿.
# {{ }}는 f-string이 아니라 .format()을 쓰기 때문에, JSON 예시 안의 실제 중괄호는
# 이스케이프({{ / }})로 표기하고, 실제로 치환될 {transcript}만 홑겹 중괄호로 남긴다.
# "다른 설명 없이 JSON 객체 하나만 출력해"라고 못박아서 파싱하기 쉬운 순수 JSON
# 응답을 유도한다(그래도 100% 보장되지 않으므로 아래 _extract_json에서 방어한다).
SUMMARY_PROMPT = """다음은 회의 음성을 그대로 받아쓴 스크립트입니다. 이 내용을 분석해서 회의록에 쓸 수 있도록 요약해줘.

반드시 아래 JSON 스키마 그대로, 다른 설명 없이 JSON 객체 하나만 출력해.

{{
  "meeting_title": "회의명 (스크립트 내용을 바탕으로 추론)",
  "meeting_date": "YYYY-MM-DD (스크립트에 날짜 언급이 없으면 빈 문자열)",
  "meeting_start_time": "HH:MM 24시간 표기 (회의 시작 시각 언급이 없으면 빈 문자열)",
  "meeting_end_time": "HH:MM 24시간 표기 (회의 종료 시각 언급이 없으면 빈 문자열)",
  "attendees": ["참석자1", "참석자2"],
  "agenda": ["안건1", "안건2"],
  "discussion_summary": "회의 논의 내용을 문단으로 요약",
  "decisions": ["결정사항1", "결정사항2"],
  "action_items": [
    {{"task": "액션 아이템 내용", "owner": "담당자", "due_date": "YYYY-MM-DD 또는 빈 문자열"}}
  ]
}}

스크립트:
---
{transcript}
---
"""


class SummarizeError(RuntimeError):
    """Claude 요약 실패. 화면에 그대로 보여줄 수 있는 안내 문구를 담는다."""


# Anthropic API가 돌려주는 오류는 status code만으로는 원인이 불분명하다.
# 특히 400은 "잔액 부족"과 "잘못된 요청"이 같은 코드로 오기 때문에,
# 응답 메시지 내용까지 보고 무엇을 조치해야 하는지 구분해서 알려준다.
# 여기서 걸리는 문제는 대부분 코드가 아니라 계정/크레딧/설정 쪽이다.
_CREDIT_HINT = (
    "Anthropic 계정의 크레딧이 부족합니다."
    + NL
    + "https://console.anthropic.com/settings/billing 에서 크레딧을 충전하거나 플랜을 업그레이드해 주세요."
    + NL
    + "(STT는 OpenAI, 요약은 Anthropic으로 서로 다른 계정을 쓰므로 OpenAI 잔액과는 별개입니다.)"
)
_AUTH_HINT = (
    "Anthropic API 키 인증에 실패했습니다. .env의 ANTHROPIC_API_KEY가 유효한지 확인해 주세요."
    + NL
    + "키 재발급: https://console.anthropic.com/settings/keys"
)
_MODEL_HINT = (
    "모델 이름을 찾을 수 없습니다. .env의 ANTHROPIC_MODEL 값이 올바른지 확인해 주세요."
    + NL
    + "예: claude-sonnet-5, claude-opus-5, claude-haiku-4-5"
)
_RATE_HINT = "요청이 너무 잦아 일시적으로 제한되었습니다. 잠시 후 다시 시도해 주세요."


def _describe_api_error(exc: anthropic.APIStatusError) -> str:
    """Anthropic API 오류를 원인 + 조치 안내가 담긴 문구로 바꾼다."""
    # 잔액 부족은 400(invalid_request_error)으로 오고 본문 메시지로만 구분되므로
    # 상태 코드보다 메시지 내용을 먼저 확인한다.
    detail = str(getattr(exc, "message", "") or exc)
    if "credit balance is too low" in detail:
        hint = _CREDIT_HINT
    elif isinstance(exc, anthropic.AuthenticationError):
        hint = _AUTH_HINT
    elif isinstance(exc, anthropic.NotFoundError):
        hint = _MODEL_HINT
    elif isinstance(exc, anthropic.RateLimitError):
        hint = _RATE_HINT
    elif exc.status_code >= 500:
        hint = "Anthropic 서버 측 오류입니다. 잠시 후 다시 시도해 주세요."
    else:
        hint = ""

    message = f"회의 요약 실패 (HTTP {exc.status_code}): {detail}"
    if hint:
        message += NL + NL + hint
    return message


def _extract_json(text: str) -> dict:
    """Claude 응답 텍스트에서 JSON 객체 부분만 뽑아 파싱한다.

    프롬프트에서 "JSON만 출력"하라고 지시했지만, 모델이 앞뒤로 부가 설명이나
    마크다운 코드펜스(```json ... ```)를 덧붙이는 경우가 있어, 정규식으로
    가장 바깥쪽 중괄호 블록만 찾아내는 방식으로 방어한다.
    """
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"Claude 응답에서 JSON을 찾지 못했습니다: {text!r}")
    return json.loads(match.group(0))


def _as_list(value) -> list:
    """리스트 필드의 타입을 방어적으로 정규화한다.

    Claude가 스키마상 배열이어야 할 필드(attendees/agenda/decisions)를
    가끔 "박창민 팀장, 김개발 대리" 같은 콤마 구분 문자열로 반환하는 경우가
    실제로 관측되었다. 이를 그대로 두면 이후 ", ".join()이 문자열의 글자 하나
    하나에 적용되어 "박, 창, 민, ..." 처럼 완전히 깨진 결과가 나온다.
    그래서 문자열이면 콤마로 쪼개 리스트로 변환하고, 이미 리스트면 그대로,
    그 외 타입(None 등)이면 빈 리스트로 안전하게 맞춘다.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def summarize_meeting(transcript: str, api_key: str, model: str) -> dict:
    """회의 스크립트를 Claude에 보내 구조화된 요약 dict로 변환한다.

    Args:
        transcript: STT로 변환된 회의 전체 스크립트 텍스트.
        api_key: Anthropic API 키.
        model: 사용할 Claude 모델 이름 (예: "claude-sonnet-5").

    Returns:
        SUMMARY_PROMPT의 JSON 스키마와 동일한 키를 가진 dict.
        (meeting_title, meeting_date, meeting_start_time, meeting_end_time,
        attendees, agenda, discussion_summary, decisions, action_items)
    """
    client = anthropic.Anthropic(api_key=api_key)
    try:
        message = client.messages.create(
            model=model,
            max_tokens=4000,
            messages=[{"role": "user", "content": SUMMARY_PROMPT.format(transcript=transcript)}],
        )
    except anthropic.APIStatusError as exc:
        # 크레딧 부족/인증 실패/잘못된 모델 등은 사용자가 직접 조치해야 하므로
        # 상태 코드만 노출하지 않고 무엇을 고쳐야 하는지까지 담아 다시 던진다.
        raise SummarizeError(_describe_api_error(exc)) from exc
    except anthropic.APIConnectionError as exc:
        raise SummarizeError(
            "Anthropic API에 연결하지 못했습니다. 네트워크 연결을 확인해 주세요."
        ) from exc

    # message.content는 블록(텍스트/도구 호출 등) 리스트다. 텍스트 블록만
    # 모아서 하나의 문자열로 합친다(보통은 텍스트 블록 하나뿐이다).
    text = "".join(block.text for block in message.content if block.type == "text")
    data = _extract_json(text)

    # 스키마를 따르지 않는 응답이 와도 다운스트림(엑셀/컨플루언스 생성)이
    # 깨지지 않도록 리스트 타입 필드를 한 번 더 정규화해서 반환한다.
    data["attendees"] = _as_list(data.get("attendees"))
    data["agenda"] = _as_list(data.get("agenda"))
    data["decisions"] = _as_list(data.get("decisions"))
    if not isinstance(data.get("action_items"), list):
        data["action_items"] = []

    # 모델이 시간 필드를 통째로 빠뜨리거나 null로 주는 경우가 있어, 화면 입력칸이
    # None을 받지 않도록 빈 문자열로 맞춰둔다.
    for key in ("meeting_start_time", "meeting_end_time"):
        value = data.get(key)
        data[key] = value.strip() if isinstance(value, str) else ""

    return data
