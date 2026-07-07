"""Confluence Cloud REST API 연동 서비스.

이메일 + API 토큰을 이용한 Basic Auth 방식으로 인증한다(OAuth 3LO 대신 이
방식을 선택한 이유는 1인/사내용 자동화 스크립트에는 브라우저 인가 절차와
refresh token 관리가 필요한 OAuth보다 훨씬 간단하기 때문).

이 모듈이 하는 일은 두 가지다.
1) ConfluenceClient: 특정 스페이스의 부모 페이지 밑에 새 회의록 페이지를 생성.
2) build_storage_html: 회의록 필드 dict를 Confluence 저장 형식(XHTML)의
   표 HTML로 변환 (회사 엑셀 양식과 동일한 레이아웃으로 보이도록 구성).
"""

from html import escape

import requests
from requests.auth import HTTPBasicAuth


class ConfluenceClient:
    """Confluence Cloud REST API(`/rest/api/content`)를 감싼 얇은 클라이언트."""

    def __init__(self, base_url: str, email: str, api_token: str):
        # base_url 예: https://회사.atlassian.net/wiki (끝에 슬래시가 있어도 없어도 동작하도록 제거)
        self.base_url = base_url.rstrip("/")
        # Confluence Cloud는 "이메일 + API 토큰" 조합을 HTTP Basic Auth로 받는다.
        self.auth = HTTPBasicAuth(email, api_token)
        self.headers = {"Content-Type": "application/json"}

    def find_page_id(self, space_key: str, title: str) -> str:
        """스페이스 키 + 제목으로 기존 페이지를 검색해서 페이지 ID를 반환한다.

        새 회의록 페이지를 만들 때 "어느 페이지의 하위 페이지로 넣을지"를
        지정하려면 Confluence 내부 페이지 ID가 필요한데, 사용자는 제목만
        알고 있으므로 이 함수로 제목 -> ID 변환을 해준다.
        (예: CONFLUENCE_PARENT_PAGE_TITLE="101.회의록" -> 해당 페이지의 ID)
        """
        resp = requests.get(
            f"{self.base_url}/rest/api/content",
            params={"spaceKey": space_key, "title": title},
            auth=self.auth,
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()  # 401/403/404 등은 여기서 예외로 바로 드러난다
        results = resp.json().get("results", [])
        if not results:
            raise ValueError(f"페이지를 찾지 못했습니다: space={space_key} title={title!r}")
        return results[0]["id"]

    def create_child_page(self, space_key: str, parent_title: str, new_title: str, html_body: str) -> dict:
        """parent_title 페이지의 하위 페이지로 새 회의록 페이지를 생성한다.

        Args:
            space_key: 대상 스페이스 키 (예: "~712020..." 같은 개인 스페이스 키도 가능).
            parent_title: 하위 페이지로 붙일 부모 페이지의 제목 (예: "101.회의록").
            new_title: 새로 만들 페이지의 제목 (예: "2026-07-02_차세대 프로젝트 주간 회의").
            html_body: Confluence storage format(XHTML)으로 작성된 본문 내용.

        Returns:
            생성된 페이지에 대한 Confluence REST API 응답(JSON)을 dict로 반환.
            호출 측(app.py)에서 result["_links"]["webui"]로 페이지 URL을 만든다.
        """
        parent_id = self.find_page_id(space_key, parent_title)
        payload = {
            "type": "page",
            "title": new_title,
            "space": {"key": space_key},
            "ancestors": [{"id": parent_id}],  # 이 배열에 부모 ID를 넣으면 그 하위 페이지로 생성된다
            "body": {"storage": {"value": html_body, "representation": "storage"}},
        }
        resp = requests.post(
            f"{self.base_url}/rest/api/content",
            json=payload,
            auth=self.auth,
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


def _multiline_html(text: str) -> str:
    """여러 줄 텍스트를 Confluence storage format(XHTML)에 맞게 변환한다.

    HTML은 문자열 안의 개행문자(\\n)를 자동으로 줄바꿈으로 표시해주지 않으므로,
    줄마다 <br/>로 이어 붙여야 화면에서도 줄바꿈이 그대로 보인다. 특수문자
    (<, >, & 등)는 escape()로 이스케이프해서 HTML 인젝션을 방지한다.
    """
    return "<br/>".join(escape(line) for line in text.splitlines()) or "-"


def build_storage_html(fields: dict) -> str:
    """평탄화된 회의록 필드 dict(excel_export.build_excel_fields와 동일한 형태)를
    Confluence storage format(XHTML) 표로 렌더링한다.

    회사 엑셀 회의록 양식과 동일하게 보이도록 레이아웃을 맞췄다.
    - 맨 위: "회의록" 제목 배너 (병합된 헤더 행)
    - 프로젝트명/프로젝트 단계/활동명 - 한 행에 3쌍(라벨-값)
    - 회의일시/회의장소/주관사 - 한 행에 3쌍(라벨-값)
    - 참석자/회의제목/회의내용 - 각각 전체 폭 한 행
    - Action Item - 같은 표의 마지막 행 (별도 표로 분리하면 위 행과 열 너비가
      어긋나 보이므로, 하나의 표 안에 이어 붙여서 시각적으로 자연스럽게 연결)

    colgroup으로 각 열의 폭을 퍼센트로 고정해서, 위 아래 행의 라벨/값 칸
    경계가 서로 어긋나지 않고 깔끔하게 정렬되도록 한다.
    """
    # 라벨(th) 셀에 공통으로 적용할 배경색 스타일. f-string 안에서 반복 사용하기 위해 변수로 뺐다.
    label = ' style="background-color:#f2f2f2;"'

    return f"""
<table style="width:100%;table-layout:fixed;">
  <colgroup>
    <col style="width:15%;" /><col style="width:18%;" />
    <col style="width:15%;" /><col style="width:18%;" />
    <col style="width:15%;" /><col style="width:19%;" />
  </colgroup>
  <tbody>
    <tr><th colspan="6" style="text-align:center;background-color:#dce6f1;"><strong>회의록</strong></th></tr>
    <tr>
      <th{label}>*프로젝트명</th><td>{escape(fields.get('project_name', ''))}</td>
      <th{label}>*프로젝트 단계</th><td>{escape(fields.get('project_phase', ''))}</td>
      <th{label}>*활동명</th><td>{escape(fields.get('activity_name', ''))}</td>
    </tr>
    <tr>
      <th{label}>*회의일시</th><td>{escape(fields.get('meeting_date', ''))}</td>
      <th{label}>*회의장소</th><td>{escape(fields.get('meeting_location', ''))}</td>
      <th{label}>*주관사</th><td>{escape(fields.get('organizer', ''))}</td>
    </tr>
    <tr><th{label}>*참석자</th><td colspan="5">{escape(fields.get('attendees', ''))}</td></tr>
    <tr><th{label}>*회의제목</th><td colspan="5">{escape(fields.get('meeting_title', ''))}</td></tr>
    <tr><th{label}>*회의내용</th><td colspan="5">{_multiline_html(fields.get('discussion_summary', ''))}</td></tr>
    <tr><th{label}>Action Item</th><td colspan="5">{_multiline_html(fields.get('action_items_text', ''))}</td></tr>
  </tbody>
</table>
"""
