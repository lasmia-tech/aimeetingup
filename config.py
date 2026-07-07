"""애플리케이션 전역 설정을 로드하는 모듈.

.env 파일(로컬 개발) 또는 Streamlit Cloud의 Secrets(배포 환경) 중
어디서 값을 가져오든 나머지 코드는 항상 `settings.xxx` 형태로 동일하게
사용할 수 있도록, 두 경로를 os.environ으로 일원화한다.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# 로컬 개발 환경: 프로젝트 루트의 .env 파일을 읽어서 os.environ에 채워 넣는다.
# (.env 파일이 없으면 아무 동작도 하지 않고 조용히 넘어간다)
load_dotenv()

try:
    # Streamlit Community Cloud 배포 환경: 값이 .env가 아니라 Streamlit의
    # "Secrets" 설정(TOML 형식)으로 주입되고, st.secrets를 통해서만 접근할 수 있다.
    # 여기서 st.secrets의 모든 키를 os.environ으로 복사해두면, 아래 Settings
    # 클래스는 로컬/클라우드 구분 없이 항상 os.getenv()만 쓰면 된다.
    import streamlit as st

    for _key, _value in st.secrets.items():
        # setdefault: 이미 .env/OS 환경변수로 값이 있으면 덮어쓰지 않는다.
        os.environ.setdefault(_key, str(_value))
except Exception:
    # 로컬 개발 환경에서는 .streamlit/secrets.toml이 없어서 st.secrets 접근 시
    # 예외가 발생할 수 있다. 이 경우 위 load_dotenv() 결과만 사용하면 되므로 무시한다.
    pass


@dataclass
class Settings:
    """환경변수 값을 담는 설정 객체. 앱 전체에서 settings.xxx로 참조한다."""

    # --- STT (음성 -> 텍스트, OpenAI Whisper API) ---
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")

    # --- 회의 요약 (Claude / Anthropic API) ---
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

    # --- Confluence Cloud 연동 (API 토큰 방식 인증) ---
    confluence_base_url: str = os.getenv("CONFLUENCE_BASE_URL", "")  # 예: https://회사.atlassian.net/wiki
    confluence_email: str = os.getenv("CONFLUENCE_EMAIL", "")  # Atlassian 로그인 이메일 (Basic Auth의 아이디 역할)
    confluence_api_token: str = os.getenv("CONFLUENCE_API_TOKEN", "")  # Atlassian API 토큰 (Basic Auth의 비밀번호 역할)
    confluence_space_key: str = os.getenv("CONFLUENCE_SPACE_KEY", "")  # 회의록을 생성할 스페이스 키
    confluence_parent_page_title: str = os.getenv(
        "CONFLUENCE_PARENT_PAGE_TITLE", "101.회의록"
    )  # 새 회의록 페이지를 하위 페이지로 붙일 부모 페이지 제목

    # --- 엑셀 회의록 양식 ---
    excel_template_path: str = os.getenv(
        "EXCEL_TEMPLATE_PATH", "templates/meeting_minutes_template.xlsx"
    )  # 회사 표준 회의록 양식(.xlsx) 파일 경로
    excel_field_map_path: str = os.getenv(
        "EXCEL_FIELD_MAP_PATH", "templates/field_map.json"
    )  # 요약 필드 -> 엑셀 셀 주소 매핑 설정 파일 경로


# 모듈을 import하는 시점에 한 번만 생성해서 앱 전체가 공유하는 싱글턴처럼 사용한다.
settings = Settings()
