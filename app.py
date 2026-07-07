"""회의록 자동화 Streamlit 앱.

전체 흐름은 4단계로 구성된다.
  1. 회의 음성 업로드 -> STT(Whisper)로 텍스트 변환 -> Claude로 구조화 요약
  2. 요약 내용을 화면에서 확인/직접 수정
  3. 프로젝트명/단계/활동명 등 스크립트만으로는 알 수 없는 정보를 추가 입력
  4. (a) 회사 엑셀 회의록 양식에 반영해서 다운로드
     (b) 컨플루언스 "차세대 프로젝트" 스페이스의 지정된 부모 페이지 밑에
         하위 페이지로 자동 생성

각 단계 사이의 상태는 st.session_state에 저장해서, 버튼 클릭마다 Streamlit이
스크립트를 처음부터 다시 실행해도(=rerun) 이전 단계의 결과가 유지되도록 한다.
"""

from pathlib import Path
from tempfile import NamedTemporaryFile

import streamlit as st

from config import settings
from services.audio_meta import default_meeting_date
from services.confluence import ConfluenceClient, build_storage_html
from services.excel_export import build_excel_fields, fill_template
from services.stt import transcribe_audio
from services.summarize import summarize_meeting

st.set_page_config(page_title="회의록 자동화", layout="wide")
st.title("회의록 자동화")

# session_state 초기화: 위젯 값과 달리 이 값들은 버튼 클릭으로 인한 rerun에도
# 우리가 명시적으로 관리(덮어쓰기)하는 "우리 것"인 데이터이므로 최초 1회만 초기화한다.
if "transcript" not in st.session_state:
    st.session_state.transcript = ""
if "summary" not in st.session_state:
    st.session_state.summary = None

# ── 1단계: 음성 업로드 -> STT -> 요약 ─────────────────────────────────────
st.header("1. 음성 업로드 → 텍스트 변환 + 요약")
audio_file = st.file_uploader("회의 음성 파일", type=["mp3", "wav", "m4a", "mp4", "webm"])

# 파일이 없으면 버튼 자체를 비활성화해서 오작동을 방지한다.
if st.button("텍스트 변환 + 요약 실행", disabled=audio_file is None):
    if not settings.openai_api_key or not settings.anthropic_api_key:
        st.error("OPENAI_API_KEY / ANTHROPIC_API_KEY가 .env에 설정되어 있어야 합니다.")
    else:
        # OpenAI Whisper API는 파일 "경로"가 아니라 실제 바이트를 필요로 하므로,
        # 업로드된 바이트를 임시 파일로 한 번 디스크에 써서 그 경로를 넘긴다.
        with NamedTemporaryFile(delete=False, suffix=Path(audio_file.name).suffix) as tmp:
            tmp.write(audio_file.getvalue())
            tmp_path = tmp.name

        # 회의일시 기본값 후보: 음성 파일 자체에 녹음일 메타데이터가 있으면 그 값,
        # 없으면 지금(업로드/처리 시각)을 사용한다. Claude가 스크립트 내용에서
        # 날짜를 이미 추출했다면 아래에서 그 값을 더 우선시한다.
        recorded_date = default_meeting_date(tmp_path)

        with st.spinner("음성을 텍스트로 변환하는 중..."):
            st.session_state.transcript = transcribe_audio(tmp_path, settings.openai_api_key)
        with st.spinner("회의 내용을 요약하는 중..."):
            st.session_state.summary = summarize_meeting(
                st.session_state.transcript, settings.anthropic_api_key, settings.anthropic_model
            )

        # Claude가 스크립트에서 명시적 날짜를 찾지 못해 meeting_date가 빈 값일 때만
        # 파일 메타데이터/업로드 시각으로 채운다(내용 기반 값이 있으면 그게 더 정확하므로 유지).
        if not st.session_state.summary.get("meeting_date"):
            st.session_state.summary["meeting_date"] = recorded_date

        st.success("변환 및 요약이 완료되었습니다.")

# STT 결과가 있을 때만 스크립트 확인/수정 영역을 보여준다.
if st.session_state.transcript:
    with st.expander("전체 스크립트 보기 / 직접 수정", expanded=True):
        # 이 text_area는 읽기 전용이 아니라 편집 가능하며, 반환값을 다시
        # session_state.transcript에 대입해서 사용자의 수정 내용이 즉시 반영되게 한다.
        st.session_state.transcript = st.text_area(
            "스크립트", st.session_state.transcript, height=200, label_visibility="collapsed"
        )
        # 음성을 다시 변환하지 않고, 수정된 텍스트만으로 Claude 요약만 다시 돌리고 싶을 때 사용.
        if st.button("이 텍스트로 다시 요약"):
            if not settings.anthropic_api_key:
                st.error("ANTHROPIC_API_KEY가 .env에 설정되어 있어야 합니다.")
            else:
                with st.spinner("회의 내용을 요약하는 중..."):
                    st.session_state.summary = summarize_meeting(
                        st.session_state.transcript, settings.anthropic_api_key, settings.anthropic_model
                    )
                st.success("수정한 텍스트로 다시 요약했습니다.")

# ── 2단계: 요약 내용 확인/수정 ─────────────────────────────────────────
# summary는 매 rerun마다 아래 위젯들에 의해 다시 채워지므로, 사용자가 화면에서
# 값을 고치면 다음 rerun에서 그 수정된 값이 그대로 summary dict에 반영된다.
summary = st.session_state.summary
if summary:
    st.header("2. 요약 내용 확인/수정")
    summary["meeting_title"] = st.text_input("회의명", summary.get("meeting_title", ""))
    summary["meeting_date"] = st.text_input("일시 (YYYY-MM-DD)", summary.get("meeting_date", ""))

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
    # 이 fields dict가 엑셀 셀 채우기와 컨플루언스 HTML 생성 양쪽의 공통 입력이 된다.
    fields = build_excel_fields(summary, project_name, project_phase, activity_name, meeting_location, organizer)

    # ── 4-a단계: 엑셀 회의록 생성 ────────────────────────────────────────
    st.header("4. 엑셀 회의록 생성")
    if st.button("엑셀 파일 생성"):
        try:
            output_path = fill_template(
                fields,
                settings.excel_template_path,
                settings.excel_field_map_path,
                f"output/{summary['meeting_title'] or 'meeting'}_{summary['meeting_date'] or ''}.xlsx",
            )
            with open(output_path, "rb") as f:
                st.download_button("엑셀 파일 다운로드", f, file_name=Path(output_path).name)
        except FileNotFoundError as e:
            # 회사 양식 파일이나 field_map.json이 아직 준비되지 않은 경우를 위한 안내.
            st.error(
                f"엑셀 양식 파일 또는 필드 매핑 파일을 찾을 수 없습니다: {e}. "
                f"templates/ 폴더에 회의록 양식 파일과 field_map.json을 준비해주세요."
            )

    # ── 4-b단계: 컨플루언스에 회의록 페이지 생성 ─────────────────────────
    st.header("5. 컨플루언스에 회의록 페이지 생성")
    if st.button("컨플루언스에 게시"):
        required = [
            settings.confluence_base_url,
            settings.confluence_email,
            settings.confluence_api_token,
            settings.confluence_space_key,
        ]
        if not all(required):
            st.error("컨플루언스 접속 정보(.env의 CONFLUENCE_* 값)가 모두 설정되어야 합니다.")
        elif not fields["meeting_date"].strip() or not fields["meeting_title"].strip():
            # 페이지 제목이 "일시_회의명" 형식이므로 둘 다 없으면 의미 없는 제목이 만들어진다.
            st.error("페이지 제목은 '회의일시_회의명'으로 생성됩니다. 위의 '일시'와 '회의명' 항목을 먼저 채워주세요.")
        else:
            try:
                client = ConfluenceClient(
                    settings.confluence_base_url, settings.confluence_email, settings.confluence_api_token
                )
                # 페이지 제목 형식: "2026-07-02_차세대 프로젝트 주간 회의" (사용자 요청에 따라 확정)
                title = f"{fields['meeting_date'].strip()}_{fields['meeting_title'].strip()}"
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
            except Exception as e:
                # 인증 실패, 부모 페이지 못 찾음, 네트워크 오류 등을 사용자에게 그대로 노출해서
                # 어디서 막혔는지 바로 알 수 있게 한다.
                st.error(f"컨플루언스 페이지 생성에 실패했습니다: {e}")
