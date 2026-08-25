import os
import sys

from law_effective_monitor import send_enforcement, send_promulgation


def required(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise ValueError(f"필수 테스트 입력이 없습니다: {name}")
    return value


def main() -> int:
    alert_type = required("TEST_ALERT_TYPE")
    law_name = required("TEST_LAW_NAME")
    promulgation_date = required("TEST_PROMULGATION_DATE")
    enforcement_date = required("TEST_ENFORCEMENT_DATE")
    promulgation_no = required("TEST_PROMULGATION_NO")
    detail_link = (os.getenv("TEST_DETAIL_LINK") or "https://www.law.go.kr").strip()
    revision_type = (os.getenv("TEST_REVISION_TYPE") or "일부개정").strip()

    record = {
        "law_name": law_name,
        "promulgation_date": promulgation_date,
        "enforcement_date": enforcement_date,
        "promulgation_no": promulgation_no,
        "detail_link": detail_link,
        "revision_type": revision_type,
    }

    if alert_type == "공포":
        send_promulgation(record, test_mode=True)
        print("[INFO] 공포 테스트 이메일/텔레그램 발송 완료")
        return 0
    if alert_type == "시행":
        # 테스트에서는 입력한 시행일을 '오늘'로 간주해 실제 운영 문구를 그대로 확인한다.
        today = "".join(ch for ch in enforcement_date if ch.isdigit())[:8]
        send_enforcement(record, test_mode=True, today=today)
        print("[INFO] 시행 테스트 이메일/텔레그램 발송 완료")
        return 0

    raise ValueError(f"지원하지 않는 테스트 종류입니다: {alert_type}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
