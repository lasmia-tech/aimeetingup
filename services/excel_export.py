"""Claude 요약 결과 + 사용자 입력을 평탄화된 필드 dict로 합치는 서비스.

이 fields dict는 컨플루언스 페이지 HTML 생성(services/confluence.py)의
공통 입력으로 쓰인다.
"""


def _format_meeting_datetime(meeting_date: str, start_time: str, end_time: str) -> str:
    """날짜 + 시작/종료 시간을 회의일시 한 칸에 넣을 문자열로 합친다.

    엑셀 양식과 컨플루언스 표에는 "회의일시" 칸이 하나뿐이라 별도 열을 만들 수
    없으므로, "2026-09-01 14:00~15:30" 형태로 이어 붙인다. 시간을 입력하지
    않았으면 날짜만, 종료 시간만 비어 있으면 시작 시간까지만 표시한다.
    """
    date_part = meeting_date.strip()
    start, end = start_time.strip(), end_time.strip()

    if start and end:
        time_part = f"{start}~{end}"
    else:
        # 둘 중 하나만 있으면 있는 쪽만 쓴다(빈 물결표가 남지 않도록).
        time_part = start or end

    return " ".join(part for part in (date_part, time_part) if part)


def build_excel_fields(
    summary: dict,
    project_name: str,
    project_phase: str,
    activity_name: str,
    meeting_location: str,
    organizer: str,
    meeting_start_time: str = "",
    meeting_end_time: str = "",
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
        meeting_start_time: 회의 시작 시간 ("HH:MM", 없으면 빈 문자열).
        meeting_end_time: 회의 종료 시간 ("HH:MM", 없으면 빈 문자열).

    Returns:
        엑셀 셀/컨플루언스 HTML 표에 그대로 넣을 수 있는, 모든 값이 문자열인
        평탄화된 dict. (project_name, project_phase, activity_name,
        meeting_date, meeting_date_only, meeting_location, organizer, attendees,
        meeting_title, discussion_summary, action_items_text)

        meeting_date는 시간까지 합친 표시용 문자열이고, meeting_date_only는
        날짜만 담은 값이다(컨플루언스 페이지 제목처럼 시간이 들어가면 곤란한
        곳에서 쓴다).
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
        "meeting_date": _format_meeting_datetime(
            summary.get("meeting_date", ""),
            meeting_start_time,
            meeting_end_time,
        ),
        # 페이지 제목("일시_회의명")에는 시간을 넣지 않으므로 날짜만 따로 남겨둔다.
        "meeting_date_only": summary.get("meeting_date", ""),
        "meeting_location": meeting_location,
        "organizer": organizer,
        # attendees는 리스트이므로 엑셀/컨플루언스에 넣기 위해 콤마로 이어 붙인다.
        "attendees": ", ".join(summary.get("attendees", [])),
        "meeting_title": summary.get("meeting_title", ""),
        "discussion_summary": "\n\n".join(content_parts),
        "action_items_text": action_items_text,
    }
