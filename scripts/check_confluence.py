"""컨플루언스 연결 상태 점검 스크립트.

사용법:
  python scripts/check_confluence.py

.env의 CONFLUENCE_* 값으로 실제 컨플루언스에 읽기 전용 호출을 보내서,
막히는 지점이 어디인지 단계별로 알려준다. 페이지를 생성하지는 않는다.

특히 중요한 것이 2단계다. 컨플루언스는 인증 실패와 권한 부족을 똑같이
403 "Current user not permitted to use Confluence"로 돌려주기 때문에,
응답 코드만 봐서는 둘을 구분할 수 없다. 그래서 일부러 틀린 토큰으로도
한 번 호출해보고, 정상 토큰일 때와 응답이 같은지를 비교한다.
- 응답이 같으면  -> 토큰이 무시되고 있다 = 인증 실패 (토큰 재발급 필요)
- 응답이 다르면  -> 인증은 됐고 권한이 없다 = 관리자에게 라이선스 요청
"""

import sys
from pathlib import Path

# scripts/ 안에서 실행해도 프로젝트 루트의 config/services를 import할 수 있게 한다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import requests
from requests.auth import HTTPBasicAuth

from config import settings
from services.confluence import ConfluenceClient, ConfluenceError


def main() -> int:
    base = settings.confluence_base_url.rstrip("/")

    print("=== 1. .env 설정 확인 ===")
    required = {
        "CONFLUENCE_BASE_URL": settings.confluence_base_url,
        "CONFLUENCE_EMAIL": settings.confluence_email,
        "CONFLUENCE_API_TOKEN": settings.confluence_api_token,
        "CONFLUENCE_SPACE_KEY": settings.confluence_space_key,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print("  ERROR: 값이 비어 있습니다:", ", ".join(missing))
        return 1
    token = settings.confluence_api_token
    print("  계정        :", settings.confluence_email)
    print("  사이트      :", base)
    print("  스페이스 키 :", settings.confluence_space_key)
    print("  부모 페이지 :", settings.confluence_parent_page_title)
    print("  토큰        :", token[:12] + "..." + token[-6:], f"(길이 {len(token)})")

    print()
    print("=== 2. 인증 실패 / 권한 부족 구분 ===")
    url = f"{base}/rest/api/space?limit=1"
    good = requests.get(url, auth=HTTPBasicAuth(settings.confluence_email, token), timeout=30)
    bad = requests.get(url, auth=HTTPBasicAuth(settings.confluence_email, "wrong-token"), timeout=30)
    print(f"  정상 토큰: {good.status_code} / 일부러 틀린 토큰: {bad.status_code}")

    if good.ok:
        print("  OK: 인증과 권한 모두 정상입니다.")
    elif good.status_code == bad.status_code:
        # 토큰을 바꿔도 결과가 같다 = 서버가 토큰을 전혀 보고 있지 않다.
        print("  ERROR: 토큰이 무시되고 있습니다 (익명 요청으로 처리됨) = 인증 실패.")
        print("         브라우저에서는 위키가 보이는데 여기서 막힌다면, 토큰이 만료/삭제됐거나")
        print("         다른 Atlassian 계정으로 발급된 토큰입니다.")
        print("         위키가 보이는 계정으로 로그인한 상태에서 토큰을 새로 발급받아")
        print("         .env의 CONFLUENCE_API_TOKEN을 교체하세요:")
        print("         https://id.atlassian.com/manage-profile/security/api-tokens")
        return 2
    else:
        print("  ERROR: 인증은 통과했지만 권한이 없습니다.")
        print("         admin.atlassian.com 에서 이 계정에 Confluence 제품 접근 권한을 부여하세요.")
        return 3

    print()
    print("=== 3. 부모 페이지 조회 ===")
    client = ConfluenceClient(base, settings.confluence_email, token)
    try:
        page_id = client.find_page_id(settings.confluence_space_key, settings.confluence_parent_page_title)
    except ConfluenceError as exc:
        print("  ERROR:", exc)
        return 4
    print(f"  OK: '{settings.confluence_parent_page_title}' 페이지를 찾았습니다 (id={page_id}).")

    print()
    print("모든 점검을 통과했습니다. 앱에서 '컨플루언스에 게시'가 정상 동작합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
