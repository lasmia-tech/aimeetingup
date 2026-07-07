"""Claude 요약 결과를 회사 표준 회의록 엑셀 양식에 채워 넣는 서비스.

실제 엑셀 양식(templates/회의록양식_샘플.xlsx)은 셀 병합이 많은 자유서식
1페이지 문서라서, "필드명 -> 셀 주소" 매핑을 담은 templates/field_map.json을
참고해 해당 셀에 문자열 값을 그대로 써 넣는 단순한 방식으로 동작한다.
(반복되는 표/행 삽입 로직은 실제 양식에 필요 없어서 만들지 않았다.)
"""

import json
from pathlib import Path

import openpyxl


def _load_field_map(field_map_path: str) -> dict:
    """필드명 -> 셀 주소 매핑이 담긴 JSON 설정 파일을 읽어온다.

    예: {"scalar_fields": {"project_name": "C3", "meeting_title": "C6", ...}}
    """
    with open(field_map_path, encoding="utf-8") as f:
        return json.load(f)


def build_excel_fields(
    summary: dict,
    project_name: str,
    project_phase: str,
    activity_name: str,
    meeting_location: str,
    organizer: str,
) -> dict:
    """Claude 요약(summary) + 사용자가 직접 입력한 프로젝트 정보를 하나로
    합쳐서, 엑셀 양식과 컨플루언스 페이지가 공통으로 쓰는 "평탄화된" 필드
    dict를 만든다. (프로젝트명/단계/활동명/장소/주관사는 회의 스크립트만으로는
    알 수 없는 정보라 Streamlit UI에서 사용자가 직접 입력받는다.)

    Args:
        summary: summarize_meeting()이 반환한 구조화 요약 dict.
        project_name: 프로젝트명 (예: "차세대 프로젝트").
        project_phase: 프로젝트 단계 (예: "요구사항 분석").
        activity_name: 활동명 (예: "요구사항 수집").
        meeting_location: 회의장소.
        organizer: 주관사.

    Returns:
        엑셀 셀/컨플루언스 HTML 표에 그대로 넣을 수 있는, 모든 값이 문자열인
        평탄화된 dict. (project_name, project_phase, activity_name,
        meeting_date, meeting_location, organizer, attendees, meeting_title,
        discussion_summary, action_items_text)
    """
    # 회사 양식에는 "회의내용" 칸 하나만 있고 안건/논의내용/결정사항이 따로
    # 나뉘어 있지 않으므로, 세 항목을 [안건]/[논의 내용]/[결정 사항] 소제목을
    # 붙인 하나의 텍스트 블록으로 합친다.
    content_parts = []
    if summary.get("agenda"):
        content_parts.append("[안건]\n" + "\n".join(f"- {a}" for a in summary["agenda"]))
    if summary.get("discussion_summary"):
        content_parts.append("[논의 내용]\n" + summary["discussion_summary"])
    if summary.get("decisions"):
        content_parts.append("[결정 사항]\n" + "\n".join(f"- {d}" for d in summary["decisions"]))

    # action_items는 (내용/담당자/기한) dict의 리스트이므로, 사람이 읽기 쉬운
    # "- 내용 (담당자: xxx, 기한: xxx)" 형태의 줄글로 펼친다.
    action_items_text = (
        "\n".join(
            f"- {item.get('task', '')} (담당자: {item.get('owner') or '-'}, 기한: {item.get('due_date') or '-'})"
            for item in summary.get("action_items", [])
        )
        or "-"  # 액션 아이템이 하나도 없으면 빈 칸 대신 "-" 표시
    )

    return {
        "project_name": project_name,
        "project_phase": project_phase,
        "activity_name": activity_name,
        "meeting_date": summary.get("meeting_date", ""),
        "meeting_location": meeting_location,
        "organizer": organizer,
        # attendees는 리스트이므로 엑셀/컨플루언스에 넣기 위해 콤마로 이어 붙인다.
        "attendees": ", ".join(summary.get("attendees", [])),
        "meeting_title": summary.get("meeting_title", ""),
        "discussion_summary": "\n\n".join(content_parts),
        "action_items_text": action_items_text,
    }


def fill_template(fields: dict, template_path: str, field_map_path: str, output_path: str) -> str:
    """평탄화된 필드 값들을 실제 엑셀 양식 파일의 지정된 셀에 채워 넣는다.

    Args:
        fields: build_excel_fields()가 만든 평탄화된 필드 dict.
        template_path: 원본 회의록 양식(.xlsx) 파일 경로 (읽기 전용으로 사용).
        field_map_path: "필드명 -> 셀 주소" 매핑이 담긴 JSON 설정 파일 경로.
        output_path: 값이 채워진 결과 파일을 저장할 경로.

    Returns:
        저장된 결과 파일의 경로(output_path와 동일한 값).
    """
    field_map = _load_field_map(field_map_path)
    wb = openpyxl.load_workbook(template_path)
    ws = wb.active  # 회의록 양식은 시트가 1개뿐이라 활성 시트만 사용

    # 매핑에 정의된 필드만 해당 셀에 덮어쓴다. 매핑에 없는 fields의 키는 무시된다.
    for field, cell in field_map.get("scalar_fields", {}).items():
        ws[cell] = fields.get(field, "")

    # output/ 폴더가 아직 없을 수 있으므로 미리 생성해둔다.
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path
