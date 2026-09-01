"""회의 스크립트에서 요구사항 목록을 추출하는 서비스.

summarize.py가 회의록 전체를 요약한다면, 이 모듈은 같은 스크립트를 다른 관점
(요구사항정의서 관점)으로 다시 읽어서 "요구사항 표"만 뽑아낸다. Claude가 리스트
형태(JSON 배열)로 응답하도록 프롬프트를 구성한다.
"""

import json
import re

import anthropic

REQUIREMENTS_PROMPT = """다음은 회의 음성을 그대로 받아쓴 스크립트입니다. 이 내용에서 언급된
요구사항(기능 요구사항/비기능 요구사항)을 찾아서 요구사항정의서에 쓸 수 있는 형태로 정리해줘.
잡담이나 요구사항이 아닌 일반 논의는 제외하고, 실제로 "무엇을 해달라/필요하다"는 취지로
언급된 내용만 뽑아줘.

반드시 아래 JSON 스키마 그대로, 다른 설명 없이 JSON 배열 하나만 출력해.
요구사항이 하나도 없으면 빈 배열 []을 출력해.

[
  {{
    "req_id": "REQ-001",
    "title": "요구사항명 (짧은 제목)",
    "description": "요구사항에 대한 구체적인 설명",
    "solution": "해결방안/고려사항 (스크립트에서 논의된 해결 방향이나 고려할 점, 없으면 빈 문자열)",
    "category_large": "업무 대분류 (스크립트 맥락상 추론되는 업무 영역, 불명확하면 빈 문자열)",
    "category_medium": "업무 중분류 (불명확하면 빈 문자열)",
    "category_small": "업무 소분류 (불명확하면 빈 문자열)",
    "type": "기능 또는 비기능 중 하나",
    "requester": "요구한 사람/부서 (스크립트에서 알 수 없으면 빈 문자열)",
    "priority": "상 또는 중 또는 하 중 하나 (명확하지 않으면 중)",
    "note": "비고 (선택, 없으면 빈 문자열)"
  }}
]

스크립트:
---
{transcript}
---
"""


def _extract_json_array(text: str) -> list:
    """Claude 응답 텍스트에서 JSON 배열 부분만 뽑아 파싱한다.

    summarize.py의 _extract_json과 같은 이유(마크다운 코드펜스, 부가 설명 등)로
    정규식 방어가 필요하다.
    """
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError(f"Claude 응답에서 JSON 배열을 찾지 못했습니다: {text!r}")
    return json.loads(match.group(0))


def extract_requirements(transcript: str, api_key: str, model: str) -> list[dict]:
    """회의 스크립트를 Claude에 보내 요구사항 목록(dict의 리스트)으로 변환한다.

    Args:
        transcript: STT로 변환된 회의 전체 스크립트 텍스트.
        api_key: Anthropic API 키.
        model: 사용할 Claude 모델 이름 (예: "claude-sonnet-5").

    Returns:
        각 항목이 req_id/title/description/category/requester/priority/note
        키를 모두 가진 dict의 리스트.
    """
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": REQUIREMENTS_PROMPT.format(transcript=transcript)}],
    )

    text = "".join(block.text for block in message.content if block.type == "text")
    data = _extract_json_array(text)

    # 스키마를 따르지 않는 응답이 와도 화면의 data_editor/엑셀 채우기가 깨지지
    # 않도록, 항목마다 모든 키가 존재하는 dict로 정규화해서 반환한다.
    normalized = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "req_id": item.get("req_id", ""),
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "solution": item.get("solution", ""),
                "category_large": item.get("category_large", ""),
                "category_medium": item.get("category_medium", ""),
                "category_small": item.get("category_small", ""),
                "type": item.get("type", "기능"),
                "requester": item.get("requester", ""),
                # 이 앱은 항상 회의 스크립트에서만 요구사항을 추출하므로 요건원천은 고정값이다.
                "source": "회의록",
                # 수용 여부는 AI가 판단할 사항이 아니라 검토자가 화면에서 직접 정하는 값이라 비워둔다.
                "acceptance": "",
                "priority": item.get("priority", "중"),
                "note": item.get("note", ""),
            }
        )
    return normalized
