"""회의록 자동화 화면.

전체 흐름은 4단계로 구성된다.
  1. 회의 음성 업로드 -> STT(Whisper)로 텍스트 변환 -> Claude로 구조화 요약
  2. 요약 내용을 화면에서 확인/직접 수정
  3. 프로젝트명/단계/활동명 등 스크립트만으로는 알 수 없는 정보를 추가 입력
  4. 컨플루언스 "차세대 프로젝트" 스페이스의 지정된 부모 페이지 밑에
     하위 페이지로 자동 생성

각 단계 사이의 상태는 st.session_state에 저장해서, 버튼 클릭마다 Streamlit이
스크립트를 처음부터 다시 실행해도(=rerun) 이전 단계의 결과가 유지되도록 한다.
모든 단계의 입력 영역은 이전 단계가 아직 비어 있어도 화면 로딩 시점부터 항상
보이며, 값이 없는 채로 직접 채워 넣는 것도 가능하다.
"""

from pathlib import Path

import streamlit as st

from config import settings
from services.confluence import ConfluenceClient, ConfluenceError, build_storage_html
from services.excel_export import build_excel_fields
from views._shared import render_transcript_section

st.title("회의록 자동화")

# session_state 초기화: 위젯 값과 달리 이 값들은 버튼 클릭으로 인한 rerun에도
# 우리가 명시적으로 관리(덮어쓰기)하는 "우리 것"인 데이터이므로 최초 1회만 초기화한다.
if "transcript" not in st.session_state:
    st.session_state.transcript = ""
if "summary" not in st.session_state:
    st.session_state.summary = {}

# ── 1단계: 음성 업로드 -> STT -> 요약 ─────────────────────────────────────
render_transcript_section(settings)

# ── 2단계: 요약 내용 확인/수정 ─────────────────────────────────────────
# summary는 매 rerun마다 아래 위젯들에 의해 다시 채워지므로, 사용자가 화면에서
# 값을 고치면 다음 rerun에서 그 수정된 값이 그대로 summary dict에 반영된다.
# summary가 아직 비어 있어도(요약 실행 전이어도) 아래 항목들은 항상 표시한다.
summary = st.session_state.summary
st.header("2. 요약 내용 확인/수정")
summary["meeting_title"] = st.text_input("회의명", summary.get("meeting_title", ""))

# 일시/시작/종료를 한 행에 나란히 둔다. 날짜와 시간은 모두 짧은 값이라
# 전체 폭을 쓸 이유가 없고, 세 값을 함께 봐야 회의 시간대가 한눈에 들어온다.
col_date, col_start, col_end = st.columns([2, 1, 1])
summary["meeting_date"] = col_date.text_input("일시 (YYYY-MM-DD)", summary.get("meeting_date", ""))
summary["meeting_start_time"] = col_start.text_input(
    "시작 시간 (HH:MM)", summary.get("meeting_start_time", "")
)
summary["meeting_end_time"] = col_end.text_input(
    "종료 시간 (HH:MM)", summary.get("meeting_end_time", "")
)

# attendees는 리스트지만 UI에서는 콤마로 구분된 한 줄 텍스트로 편집하는 게 더 편해서
# 리스트<->문자열 변환을 여기서 직접 처리한다.
attendees_text = st.text_area("참석자 (쉼표로 구분)", ", ".join(summary.get("attendees", [])))
summary["attendees"] = [a.strip() for a in attendees_text.split(",") if a.strip()]

# agenda/decisions는 한 줄에 하나씩 입력받아 리스트로 변환한다.
agenda_text = st.text_area("안건 (한 줄에 하나씩)", "\n".join(summary.get("agenda", [])))
summary["agenda"] = [a.strip() for a in agenda_text.splitlines() if a.strip()]

summary["discussion_summary"] = st.text_area(
    "논의 내용 요약", summary.get("discussion_summary", ""), height=150
)

decisions_text = st.text_area("결정 사항 (한 줄에 하나씩)", "\n".join(summary.get("decisions", [])))
summary["decisions"] = [d.strip() for d in decisions_text.splitlines() if d.strip()]

# action_items는 (내용/담당자/기한) 구조라서 표 형태로 직접 추가/삭제/수정할 수 있는
# data_editor를 사용한다. num_rows="dynamic"이라 행 추가/삭제도 가능하다.
action_items = st.data_editor(
    summary.get("action_items", []),
    num_rows="dynamic",
    column_config={
        "task": "내용",
        "owner": "담당자",
        "due_date": "기한",
    },
)
summary["action_items"] = action_items

# ── 3단계: 회의 스크립트만으로는 알 수 없는 프로젝트 정보 입력 ──────────
# 이 입력값들은 엑셀 생성(4-a)과 컨플루언스 게시(4-b) 양쪽에서 공통으로 쓰이므로,
# 두 기능의 버튼 블록보다 앞에서 한 번만 입력받고 fields로 합쳐둔다.
st.header("3. 회의 기본 정보 입력")
col1, col2, col3 = st.columns(3)
project_name = col1.text_input("프로젝트명", "차세대 프로젝트")
project_phase = col2.text_input("프로젝트단계", "")
activity_name = col3.text_input("활동명", "")
col4, col5 = st.columns(2)
meeting_location = col4.text_input("회의장소", "")
organizer = col5.text_input("주관사", "")

# summary(구조화 요약) + 위 4개 입력값을 하나의 평탄화된 dict로 합친다.
# 이 fields dict가 컨플루언스 HTML 생성의 입력이 된다.
fields = build_excel_fields(
    summary,
    project_name,
    project_phase,
    activity_name,
    meeting_location,
    organizer,
    summary.get("meeting_start_time", ""),
    summary.get("meeting_end_time", ""),
)

# ── 4단계: 컨플루언스에 회의록 페이지 생성 ───────────────────────────
st.header("4. 컨플루언스에 회의록 페이지 생성")
col_publish, col_check = st.columns([1, 1])
publish_clicked = col_publish.button("컨플루언스에 게시")
# 내 컨플루언스 스페이스로 바로 이동해서 게시된 페이지를 눈으로 확인할 수 있는 링크.
# 로그인 세션은 브라우저가 이미 가지고 있는 것을 그대로 쓰므로 별도 인증 로직은 필요 없다.
confluence_check_url = (
    f"{settings.confluence_base_url}/spaces/{settings.confluence_space_key}/overview"
    if settings.confluence_base_url and settings.confluence_space_key
    else settings.confluence_base_url
)
col_check.link_button(
    "컨플루언스 확인", confluence_check_url or "about:blank", disabled=not settings.confluence_base_url
)

if publish_clicked:
    required = [
        settings.confluence_base_url,
        settings.confluence_email,
        settings.confluence_api_token,
        settings.confluence_space_key,
    ]
    if not all(required):
        st.error("컨플루언스 접속 정보(.env의 CONFLUENCE_* 값)가 모두 설정되어야 합니다.")
    elif not fields["meeting_date_only"].strip() or not fields["meeting_title"].strip():
        # 제목이 "일시_시작시간_회의명" 형식이라 둘 중 하나만 비어도 의미 없는 제목이 된다.
        # (시작 시간은 선택이므로 비어 있어도 게시를 막지 않는다.)
        st.error("페이지 제목은 '일시_시작시간_회의명'으로 생성됩니다. 위의 '일시'와 '회의명' 항목을 먼저 채워주세요.")
    else:
        try:
            client = ConfluenceClient(
                settings.confluence_base_url, settings.confluence_email, settings.confluence_api_token
            )
            # 페이지 제목 형식: "일시_시작시간_회의명" (예: "2026-09-01_14:00_주간 회의").
            # 시작 시간을 입력하지 않았으면 밑줄이 겹치지 않도록 그 자리를 통째로 뺀다.
            title_parts = [
                fields["meeting_date_only"].strip(),
                summary.get("meeting_start_time", "").strip(),
                fields["meeting_title"].strip(),
            ]
            title = "_".join(part for part in title_parts if part)
            html_body = build_storage_html(fields)
            result = client.create_child_page(
                settings.confluence_space_key,
                settings.confluence_parent_page_title,
                title,
                html_body,
            )
            # Confluence REST 응답의 _links.webui는 사이트 루트 기준 상대경로라서
            # base_url과 이어붙여야 실제로 열어볼 수 있는 전체 URL이 된다.
            page_link = f"{settings.confluence_base_url}{result['_links']['webui']}"
            st.success(f"페이지가 생성되었습니다: {page_link}")
        except ConfluenceError as e:
            # 원인(Confluence가 돌려준 메시지)과 조치 방법이 이미 담긴 문구이므로
            # 군더더기 없이 그대로 보여준다.
            st.error(str(e))
        except Exception as e:
            # 네트워크 단절, 타임아웃 등 API 응답 자체를 받지 못한 경우.
            st.error(f"컨플루언스 페이지 생성에 실패했습니다: {e}")
