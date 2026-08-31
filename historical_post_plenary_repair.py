import os

import requests

import hub_notify
import law_effective_monitor as lem
import monitor
import post_plenary
from historical_hub_realdata_e2e import clean, hub_id, load_bill, norm_date, send_real_stage

ALT_SUCCESSOR_NO = "2216767"
EXPECTED_GOV_TRANSFER = "2026-02-27"
EXPECTED_PROMULGATION = "2026-03-10"
EXPECTED_PROMULGATION_NO = "21444"
EXPECTED_ENFORCEMENT = "2026-09-11"


def assert_equal(label, actual, expected):
    if clean(actual) != clean(expected):
        raise RuntimeError(f"{label} 불일치: actual={actual!r}, expected={expected!r}")
    print(f"[PASS] {label}: {actual}")


def main():
    case_id = clean(os.getenv("TEST_CASE_ID"))
    if not case_id:
        raise RuntimeError("TEST_CASE_ID is required")

    session = requests.Session()
    session.headers.update(monitor.HEADERS)
    try:
        bill = load_bill(session, ALT_SUCCESSOR_NO)
        source_id = hub_id(case_id, "ALT")
        print(f"[INFO] post_only / actual_bill={bill['bill_no']} / hub_id={source_id}")

        post = post_plenary.fetch_post_plenary_status(bill, session=session) or {}
        assert_equal("정부이송일", norm_date(post.get("government_transfer_date")), EXPECTED_GOV_TRANSFER)
        assert_equal("공포일자", norm_date(post.get("promulgation_date")), EXPECTED_PROMULGATION)
        assert_equal("공포번호", clean(post.get("promulgation_no")), EXPECTED_PROMULGATION_NO)
        print(f"[PASS] 후속단계 원천: {post.get('post_plenary_source') or '-'} / {post.get('post_plenary_url') or '-'}")

        base = {**bill, "hub_source_id": source_id}
        send_real_stage(
            base,
            source_id,
            "정부이송",
            EXPECTED_GOV_TRANSFER,
            "government_transfer_date",
        )

        oc = monitor.required_env("LAW_API_OC")
        verified = lem.verify_promulgation(
            session,
            oc,
            bill["matched_law"],
            {
                "promulgation_date": post.get("promulgation_date"),
                "promulgation_no": post.get("promulgation_no"),
            },
        )
        if not verified:
            raise RuntimeError("법제처 공포 교차검증 실패")

        assert_equal("법제처 공포일자", norm_date(verified.get("promulgation_date")), EXPECTED_PROMULGATION)
        assert_equal("법제처 공포번호", clean(verified.get("promulgation_no")), EXPECTED_PROMULGATION_NO)
        assert_equal("법제처 시행일자", norm_date(verified.get("enforcement_date")), EXPECTED_ENFORCEMENT)

        detail_link = verified.get("detail_link") or lem.public_law_link(verified)
        common_extra = {
            "promulgation_date": EXPECTED_PROMULGATION,
            "promulgation_no": EXPECTED_PROMULGATION_NO,
            "enforcement_date": EXPECTED_ENFORCEMENT,
            "detail_link": detail_link,
        }
        send_real_stage(base, source_id, "공포", EXPECTED_PROMULGATION, "promulgation_date", common_extra)
        send_real_stage(base, source_id, "시행", EXPECTED_ENFORCEMENT, "enforcement_date", common_extra)
        print("[SUCCESS] 2216767 정부이송 → 공포 → 시행 실데이터 허브 E2E 완료")
    finally:
        session.close()


if __name__ == "__main__":
    main()
