"""요구사항정의서 생성 화면.

이 화면 자체에서 회의 음성을 업로드해 텍스트 변환/요약을 실행할 수 있다.
session_state.transcript/summary는 앱 전체가 공유하므로, '회의록 생성'
화면에서 이미 변환을 마쳤다면 그 내용이 그대로 이어서 보인다. 이후 같은
스크립트를 Claude로 다시 읽어 요구사항 목록만 별도로 추출한 뒤 요구사항정의서
엑셀 양식에 채워 넣는다.
"""

from datetime import date
from pathlib import Path

import streamlit as st

from config import settings
from services.requirements import extract_requirements
from services.requirements_export import fill_requirements_template
from views._shared import render_transcript_section

st.title("요구사항정의서 생성")

if "transcript" not in st.session_state:
    st.session_state.transcript = ""
if "summary" not in st.session_state:
    st.session_state.summary = {}
if "requirements" not in st.session_state:
    st.session_state.requirements = []

# ── 1단계: 음성 업로드 -> STT -> 요약 ─────────────────────────────────────
summary_updated = render_transcript_section(settings)

transcript = st.session_state.transcript


def _run_extraction() -> None:
    with st.spinner("회의 내용에서 요구사항을 추출하는 중..."):
        st.session_state.requirements = extract_requirements(
            transcript, settings.anthropic_api_key, settings.anthropic_model
        )
    st.success(f"{len(st.session_state.requirements)}건의 요구사항을 추출했습니다.")


# ── 2단계: AI 요구사항 추출 ─────────────────────────────────────────────
st.header("2. 회의 요약에서 요구사항 추출")

# 텍스트 변환/요약이 방금 끝났으면(위 1단계에서), 버튼을 누르지 않아도 바로 이어서 추출한다.
if summary_updated and transcript.strip():
    if not settings.anthropic_api_key:
        st.error("ANTHROPIC_API_KEY가 .env에 설정되어 있어야 합니다.")
    else:
        _run_extraction()

# 추출을 다시 돌리고 싶을 때(스크립트를 손으로 고친 뒤 등)를 위한 수동 버튼은 그대로 둔다.
if st.button("요구사항 추출 실행", disabled=not transcript.strip()):
    if not settings.anthropic_api_key:
        st.error("ANTHROPIC_API_KEY가 .env에 설정되어 있어야 합니다.")
    else:
        _run_extraction()

# ── 3단계: 추출 결과 확인/수정 ───────────────────────────────────────────
st.header("3. 요구사항 목록 확인/수정")
requirements = st.data_editor(
    st.session_state.requirements,
    num_rows="dynamic",
    column_config={
        "req_id": "요구사항ID",
        "title": "요구사항명",
        "description": "요구사항설명",
        "solution": "해결방안/고려사항",
        "category_large": "업무구분(대분류)",
        "category_medium": "업무구분(중분류)",
        "category_small": "업무구분(소분류)",
        "type": st.column_config.SelectboxColumn("구분", options=["기능", "비기능"]),
        "requester": "요구자",
        "source": st.column_config.SelectboxColumn(
            "요건원천", options=["회의록", "인터뷰", "설문", "기타"]
        ),
        "acceptance": st.column_config.SelectboxColumn("수용여부", options=["", "예", "아니오", "보류"]),
        "priority": st.column_config.SelectboxColumn("우선순위", options=["상", "중", "하"]),
        "note": "비고",
    },
    column_order=[
        "req_id",
        "title",
        "description",
        "solution",
        "category_large",
        "category_medium",
        "category_small",
        "type",
        "requester",
        "source",
        "acceptance",
        "priority",
        "note",
    ],
)
st.session_state.requirements = requirements

# ── 4단계: 엑셀 생성 ─────────────────────────────────────────────────────
st.header("4. 요구사항정의서 엑셀 생성")
project_name = st.text_input("프로젝트명 (파일명에만 사용)", "차세대 프로젝트")
prepared_date = st.text_input("작성일 (파일명에만 사용, YYYY-MM-DD)", date.today().isoformat())

if st.button("엑셀 파일 생성"):
    if not requirements:
        st.error("요구사항이 하나도 없습니다. 먼저 추출을 실행하거나 직접 행을 추가해주세요.")
    else:
        try:
            output_path = fill_requirements_template(
                requirements,
                settings.requirements_template_path,
                settings.requirements_field_map_path,
                f"output/요구사항정의서_{project_name or 'project'}_{prepared_date}.xlsx",
            )
            with open(output_path, "rb") as f:
                st.download_button("요구사항정의서 다운로드", f, file_name=Path(output_path).name)
        except FileNotFoundError as e:
            st.error(
                f"요구사항정의서 양식 파일 또는 필드 매핑 파일을 찾을 수 없습니다: {e}. "
                f"templates/ 폴더를 확인해주세요."
            )
