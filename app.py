"""회의록 자동화 앱 진입점.

사이드바 메뉴(페이지) 라우팅만 담당한다. 실제 화면 구현은 views/ 아래
각 모듈에 있으며, 새 메뉴 항목은 아래 pages 딕셔너리의 "산출물 자동생성"
목록에 st.Page를 추가하면 된다.
"""

import streamlit as st

st.set_page_config(page_title="회의록 자동화", layout="wide")

# 딕셔너리로 넘기면 키("산출물 자동생성")가 사이드바 메뉴 목록 위에 섹션
# 타이틀로 표시된다.
pages = {
    "산출물 자동생성": [
        st.Page("views/meeting_minutes.py", title="회의록 생성", icon="📝", default=True),
        st.Page("views/requirements_doc.py", title="요구사항정의서 생성", icon="📋"),
    ]
}

pg = st.navigation(pages)
pg.run()
