# assembly-law-alert

국회 Open API를 이용해 지정 15개 법률의 신규 법률안을 자동 모니터링하고 Gmail로 알림을 보내는 프로젝트입니다.

## 모니터링 법률

- 식품위생법
- 건강기능식품에 관한 법률
- 식품 등의 표시·광고에 관한 법률
- 제조물 책임법
- 자원의 절약과 재활용촉진에 관한 법률
- 농수산물의 원산지 표시 등에 관한 법률
- 독점규제 및 공정거래에 관한 법률
- 가맹사업거래의 공정화에 관한 법률
- 약관의 규제에 관한 법률
- 소비자기본법
- 하도급거래 공정화에 관한 법률
- 전자상거래 등에서의 소비자보호에 관한 법률
- 표시·광고의 공정화에 관한 법률
- 인삼산업법
- 농수산물 품질관리법

## 수집 범위

- 국회의원 발의법률안: `nzmimeepazxkubdpn`
- 정부제출/위원회안 포함 접수목록: `BILLRCP`
- 제22대 국회
- 최근 7일 데이터를 재조회하고 `BILL_ID`로 중복 제거
- 신규 건이 없으면 메일 미발송
- 최초 정상 실행은 최근 데이터를 기준값으로만 저장하고 메일은 보내지 않음

## GitHub Secrets

Repository → Settings → Secrets and variables → Actions → New repository secret에서 아래 4개를 등록합니다.

- `ASSEMBLY_API_KEY`: 열린국회정보 API 인증키
- `GMAIL_USER`: 발신 Gmail 주소
- `GMAIL_APP_PASSWORD`: Gmail 앱 비밀번호
- `MAIL_TO`: 수신 메일 주소

## 실행 시간

매일 06:30 KST에 자동 실행됩니다.

## 첫 테스트

Actions → `National Assembly Law Monitor` → Run workflow에서
`최근 7일 매칭 건을 테스트 메일로 강제 발송`을 체크하면 최근 매칭 법률안을 테스트 메일로 받을 수 있습니다.

체크하지 않고 실행하면 최초 실행 시 `seen_bills.json`만 초기화하고 과거 최근 7일 법률안은 메일로 보내지 않습니다.
