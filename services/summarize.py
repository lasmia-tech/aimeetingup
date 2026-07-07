"""회의 스크립트를 구조화된 요약(JSON)으로 변환하는 서비스.

Claude(Anthropic API)를 사용한다. 파이프라인 전체에서 "두뇌" 역할을 담당하며,
STT(services/stt.py)가 만든 텍스트를 읽고 회의록에 바로 쓸 수 있는 형태
(회의명/참석자/안건/논의내용/결정사항/액션아이템)로 정리한다.
"""

import json
import re

import anthropic

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
        (meeting_title, meeting_date, attendees, agenda, discussion_summary,
        decisions, action_items)
    """
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": SUMMARY_PROMPT.format(transcript=transcript)}],
    )

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

    return data
