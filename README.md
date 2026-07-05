# SQ 부산-오클랜드 항공권 가격 추적

싱가포르항공 PUS↔AKL 왕복(2026-12-25 출발 / 2027-01-05 귀국, 성인 3 + 아동 1) 최저가를 매일 09:05 KST에 조회해 Gmail로 발송합니다. **2026-07-31 이후 자동 중단**됩니다.

## 설정 방법 (btc-ma-alert와 동일한 방식)

1. GitHub에 새 repo 생성 (예: `sq-price-alert`) 후 이 파일들을 업로드
   - `price_check.py`
   - `.github/workflows/flight-price-alert.yml`

2. Amadeus API 키 발급 (무료)
   - https://developers.amadeus.com 가입 → My Self-Service Workspace → Create New App
   - **Production 키**로 발급 (Test 환경은 PUS-AKL 노선 데이터가 없을 수 있음)
   - 하루 1회 호출이라 무료 쿼터로 충분

3. Repo Settings → Secrets and variables → Actions에 등록:

   | Secret | 값 |
   |---|---|
   | `AMADEUS_CLIENT_ID` | Amadeus API Key |
   | `AMADEUS_CLIENT_SECRET` | Amadeus API Secret |
   | `GMAIL_USER` | 기존 btc-ma-alert와 동일 |
   | `GMAIL_APP_PASSWORD` | 기존 btc-ma-alert와 동일 |
   | `RECIPIENT_EMAIL` | 수신자 (쉼표로 여러 명 가능) |

4. Actions 탭 → "SQ PUS-AKL Price Alert" → **Run workflow**로 즉시 테스트

## 메일 내용
- 오늘 최저가, 전일 대비 증감, 추적 기간 최저가/날짜, 여정 요약
- 가격 이력은 `price_history.json`에 자동 커밋되어 누적됩니다

## 참고
- Amadeus는 GDS 기준 가격이라 싱가포르항공 홈페이지 표시가(₩7,587,200)와 차이가 날 수 있습니다. 절대값보다는 **추세(오르는지/내리는지)** 확인용으로 활용하세요.
- Production 키 발급 시 결제수단 등록을 요구할 수 있으나, 무료 쿼터 내에서는 과금되지 않습니다.
