# Anthropic 콘솔: 잔액 부족(credit/low balance) 점검 및 조치 가이드

간단 소개
- 목적: Anthropic(Claude) API 사용 중 "Your credit balance is too low" 또는 유사 경고가 뜰 때 운영자가 콘솔에서 빠르게 확인하고 즉각 조치할 수 있도록 단계별 체크리스트와 스크린샷 예시를 제공합니다.

**핵심 확인 항목**
- **로그인:** Anthropic 콘솔(https://console.anthropic.com)에 조직 계정/개인 계정으로 로그인합니다.
- **Billing/Overview:** 잔액(credit), 현재 요금제(subscription), 다음 결제일(next billing date)을 확인합니다.
- **Payment Methods:** 등록된 결제수단(카드)의 만료일/승인 상태를 확인하고 필요 시 즉시 업데이트합니다.
- **Usage 탐색:** 기간 선택(Last 24h / 7d / 30d) 후 요청량과 비용 추이를 확인해 급증 원인 파악.
- **Projects / API Keys:** 어떤 API 키(또는 프로젝트)가 트래픽을 발생시켰는지, 키별 사용량을 확인합니다.
- **API Request Logs:** 실패한 요청의 응답 코드(특히 402, 403, 429, 500 계열)와 에러 메시지(예: "insufficient", "credit", "balance")를 확인합니다.
- **Budgets & Alerts:** 계정별 예산 임계치 및 알림(Email/Slack) 설정 유무를 확인합니다.
- **Organization Billing:** 조직 계정일 경우 누가 결제 담당인지(Owner/Payer) 확인하고 연락합니다.
- **Support:** Billing 관련 긴급 문의를 보낼 수 있는 Support 티켓/이메일 경로 확인.

**콘솔에서 찾는 구체 위치(권장 순서)**
1. 화면 우측 상단 계정 메뉴 → `Billing` 또는 `Organization` 선택
2. `Billing` 탭 → `Overview`에서 현재 잔액과 최근 인보이스 확인
3. `Payment methods` 또는 `Payment settings`에서 카드/송금 정보 확인 및 업데이트
4. `Usage` 또는 `Analytics` 탭 → 시간 범위를 좁혀 최근 요청 급증 확인
5. `Projects` 또는 `API keys` → 키별 요청량/비용 필터링
6. `Logs` 또는 `API requests` → 실패한 호출의 응답 본문/코드 확인
7. `Budgets` 또는 `Alerts` → 예산 임계치 및 알람 설정 여부 확인
8. `Support` → 티켓 생성 또는 Billing 팀 이메일로 연락

**즉시(긴급) 조치 우선순위**
- **결제수단 추가/갱신:** 가장 빠르고 직접적인 해결책입니다. 콘솔의 `Payment methods`에서 카드 정보를 업데이트하세요.
- **임시 차단(Feature flag):** 서비스 중단을 막기 위해 Claude 호출을 즉시 차단하고 폴백 모델(OpenAI 등)으로 전환하세요.
- **조직 담당자에게 알림:** 결제 담당자(Owner/Payer)에게 즉시 결제 승인 요청을 합니다.
- **요청량 제한:** 문제 해결 전까지 트래픽을 줄이도록 클라이언트/서버에서 리트라이/동시요청을 제한합니다.

**오류 로그에서 볼 키워드/상태 코드(탐지 규칙)**
- **키워드(응답 메시지):** "balance", "credit", "insufficient", "payment", "billing", "quota"
- **HTTP 상태 코드:** `402`(Payment Required), `403`(Forbidden/Payment), `429`(Rate Limited)

**서비스 측 폴백(권장 코드 패턴)**
- 실패 유형 감지(에러 메시지에 키워드 포함 또는 상태 코드 402/403) → 알림 발송(메일/슬랙) → Claude 호출 비활성화 → OpenAI(혹은 캐시)로 폴백
- 로깅: 실패 응답 전체(JSON)를 저장(로그 레벨: WARN/ERROR)하고, 실패 빈도가 높으면 자동 알림

**스크린샷 예시(캡처 가이드 및 파일명 예시)**
- 1) `Billing Overview` 화면
  - 파일: `images/anthropic_billing_overview.png`
  - 캡션: 잔액(credit)과 최근 인보이스 위치를 표시(우상단 계정 메뉴 → Billing)
- 2) `Payment Methods` (카드 정보 및 만료일)
  - 파일: `images/anthropic_payment_methods.png`
  - 캡션: 등록된 결제수단과 갱신 버튼 위치 하이라이트
- 3) `Usage/Analytics` (기간별 요청량 그래프)
  - 파일: `images/anthropic_usage_graph.png`
  - 캡션: 트래픽 급증 구간을 박스로 표시하고, 해당 시간대의 프로젝트/키 필터 링크를 보여줌
- 4) `API Request Logs` (에러 상세)
  - 파일: `images/anthropic_api_error_log.png`
  - 캡션: 실패 응답의 HTTP 상태 코드와 메시지(예: "insufficient")를 확대

스크린샷 팁
- 브라우저에서 F12 개발자 툴 네트워크 탭을 열어 API 호출 요청/응답을 함께 캡처하면 문제 원인 파악에 유리합니다.
- 민감한 정보(전체 카드 번호, API 키 등)는 모자이크 처리하세요.

**Anthropic에 문의할 때 포함할 내용(티켓/이메일 템플릿)**
- **제목:** Billing urgent: Low credit — [Account/OrgName]
- **본문 필수 정보:** 계정 이메일, 조직 ID(가능하면), 발생 시각(타임존 포함), 에러 메시지 전문(로그에서 복사), 최근 인보이스 ID(있다면), 연락 가능한 담당자(이름/전화/이메일)

**운영 방어선(권장 설정)**
- 예산 임계치(예: 70%, 90%) 도달 시 이메일/슬랙 알림 자동화
- 모델별/키별 일일 한도 설정(콘솔 또는 자체 미들웨어)
- 요청 전 처리로 토큰 절감(필요 없는 컨텍스트 제거, 압축)
- 캐시 및 재사용: 동일 입력 요청은 캐시 사용

참고 파일
- 가이드 파일: [docs/anthropic_console_guide.md](docs/anthropic_console_guide.md)

---
작성자: 운영팀 가이드 자동생성
