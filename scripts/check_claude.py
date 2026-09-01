"""간단한 클로드(Anthropic) 로그인/설정 검사 스크립트.

사용법:
  1) 프로젝트 루트에 `.env` 파일을 만들고 `.env.example`를 참고해
     `ANTHROPIC_API_KEY=sk-...` 값을 넣습니다.
  2) 개발 터미널(Windows PowerShell)에서:
       python scripts/check_claude.py

이 스크립트는 네트워크 호출을 수행하지 않고, 환경 변수에 키가
설정되어 있는지와 `anthropic.Anthropic` 클라이언트 생성이 가능한지
확인합니다.
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

from config import settings

API_KEY = os.getenv("ANTHROPIC_API_KEY") or settings.anthropic_api_key

if not API_KEY:
    print("ERROR: ANTHROPIC_API_KEY가 설정되어 있지 않습니다. .env 또는 환경변수를 확인하세요.")
    print("참고: .env.example 파일을 복사해서 .env로 이름 변경한 뒤 키를 넣으세요.")
    sys.exit(1)

try:
    import anthropic

    # 클라이언트 생성(네트워크 호출은 하지 않음)
    client = anthropic.Anthropic(api_key=API_KEY)
    print("OK: Anthropic API 키가 설정되어 있으며 클라이언트 인스턴스 생성에 성공했습니다.")
    print(f"사용할 모델(설정): {settings.anthropic_model}")
except Exception as exc:
    print("ERROR: Anthropic 클라이언트 생성 중 예외가 발생했습니다:", exc)
    sys.exit(2)
