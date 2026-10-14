# 의안 2221860 원문 수집 실패 조사 (2026-10-14)

## 확인된 원인

최초 운영 실행: https://github.com/Tomm-gitt/assembly-law-alert/actions/runs/38311342998
작업 ID: 115017549736. 한국시간 2026-10-13 06:34 로그:

- 국민참여입법센터, LIKMS 모두 제안이유 및 주요내용 영역을 찾지 못함.
- source=- reason=0 main=0 ai=True model=gemini-3.6-flash content=145.
- HUB 결과 INSERTED. 빈 원문으로 AI를 호출한 것이 잘못된 부재 단정문 저장의 직접 원인.
- 해당 시점 응답 HTML은 보관되지 않아 공식 원문 공란/구조 변경/오류 페이지 여부를 구분할 수 없음.

2026-10-14 조사 환경에서는 아래 두 공식 URL 모두 HTTP 502 (Connection refused).
웹 조회 도구도 접근 실패. 사이트 전체 장애나 공식 원문 공란으로 단정하지 않음.

- https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out/2221860/detailRP
- https://likms.assembly.go.kr/bill/billDetail.do?billId=PRC_9DCD75E9C9C842F7B3307DB8456A6A&ageFrom=22&ageTo=22

기존 테스트 파일의 담합 관련 예문은 원문 증거가 아니므로 복구에 사용하지 않음.

## 수정

- 유효 원문이 없으면 AI 호출 금지. 실제 수집 실패 사유를 기록한 안내만 생성.
- 일부 섹션만 있으면 별도 이유를 생성하지 않고 확보된 원문만 비AI 구조화.
- 실패 원인에 파싱 구분, HTML 길이, SHA-256 기록. HTTP/timeout 예외 보존.
- 제목 공백 변형과 분리된 제목 인식, 본문 문장 속 공포 등으로 잘리는 문제 수정.
- AI가 원문 미기재/확인 불가를 임의로 단정하는 요약을 거부.
- HUB payload에 contentStatus/contentError/contentSource 추가. 실패 안내는 content에도 포함되어 수신측이 새 필드를 무시해도 기록됨.
- CI와 운영 전 회귀검사에 content 테스트 추가.

## 복구 경계

MASTER 36행, E=2221860, J=X, K=담합 관련 감시, 처분강화 내용으로 자사 관련없음.
공식 원문 미확보로 H의 요약 복구는 보류. 수집 실패 경위는 H36 메모에 기록.
기존 값·판정·사유·판정자·알림 상태를 수정하거나 NEW_BILL을 재전송하지 않음.

content_repair.build_master_content_patch는 의안번호·제목·이전 내용 일치 및 원문 확보 여부를 검사하고 H 한 셀의 userEnteredValue 요청만 반환.
실제 쓰기 함수가 아니며, 적용자는 직전 재조회로 행 이동/동시 편집을 확인해야 함.
판정·사유·판정자·서식·큐·seen_bills에는 쓰기 권한 경로가 없음.
원문 확보 후 해당 요청으로 요약만 보완하고 행 전체 및 알림 상태를 다시 검증할 것.
