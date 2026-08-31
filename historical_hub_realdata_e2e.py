import os
import re
import time
from datetime import datetime

import requests

import hub_notify
import law_effective_monitor as lem
import monitor
import post_plenary
import status_monitor
from alternative_successor import is_alternative_reflection_result
from successor_resolution import find_verified_successor_bill


NORMAL_BILL_NO = "2201000"
ALT_ORIGINAL_BILL_NO = "2210213"
ALT_EXPECTED_SUCCESSOR_NO = "2216767"


def clean(value):
    return str(value or "").strip()


def norm_date(value):
    digits = re.sub(r"\D", "", clean(value))
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def exact_bill_row(session, bill_no):
    lookup = {"bill_no": bill_no}
    for endpoint, include_age in [
        (monitor.MEMBER_BILLS_API, True),
        (status_monitor.PROCESSED_API, True),
    ]:
        try:
            row = status_monitor.fetch_matching_row(session, endpoint, lookup, include_age=include_age)
        except Exception as exc:
            print(f"[WARN] {endpoint} 조회 실패: {bill_no} / {exc}")
            row = None
        if row and clean(row.get("BILL_NO")) == bill_no:
            return row

    data = monitor.request_api(
        session,
        monitor.RECEIPT_API,
        {"pIndex": "1", "pSize": "100", "BILL_NO": bill_no},
    )
    for row in monitor.parse_rows(data, monitor.RECEIPT_API):
        if clean(row.get("BILL_NO")) == bill_no:
            return row
    return None


def load_bill(session, bill_no):
    row = exact_bill_row(session, bill_no)
    if not row:
        raise RuntimeError(f"실제 국회 데이터에서 의안 조회 실패: {bill_no}")

    bill_id = clean(row.get("BILL_ID"))
    bill_name = clean(row.get("BILL_NAME") or row.get("BILL_NM"))
    matched_law = monitor.match_watched_law(bill_name)
    if not bill_id or not bill_name or not matched_law:
        raise RuntimeError(f"의안 식별 실패: {bill_no} / {bill_name}")

    return {
        "bill_id": bill_id,
        "bill_no": clean(row.get("BILL_NO")) or bill_no,
        "bill_name": bill_name,
        "matched_law": matched_law,
        "proposal_date": norm_date(row.get("PROPOSE_DT") or row.get("PPSL_DT")),
        "committee": clean(row.get("COMMITTEE") or row.get("CURR_COMMITTEE")),
        "proposer": clean(row.get("PROPOSER") or row.get("RST_PROPOSER") or row.get("PUBL_PROPOSER") or row.get("PPSR_KIND")),
        "detail_link": clean(row.get("DETAIL_LINK") or row.get("LINK_URL")),
        "status_tracking": True,
    }


def hub_id(case_id, kind):
    return f"HISTREAL_{case_id}_{kind}"


def register_one(session, case_id, kind, bill_no):
    bill = load_bill(session, bill_no)
    bill["hub_source_id"] = hub_id(case_id, kind)
    bill["process_result"] = "발의/접수"
    bill["proposal_reason_summary"] = (
        f"실제 과거 의안 {bill_no}의 원천데이터로 국회 lifecycle 감지와 허브 연동을 검증하는 테스트입니다."
    )
    bill["main_content_points"] = [
        "단계명과 날짜는 테스트 코드가 생성하지 않고 현재 운영 수집 로직이 실제 원천에서 읽습니다.",
        "후속 단계는 실제로 확인된 경우에만 허브와 Telegram에 전송합니다.",
    ]
    result = hub_notify._post(hub_notify.build_new_bill_payload(bill))
    action = hub_notify._extract_action(result)
    print(f"[REGISTER] {kind} / actual_bill={bill_no} / hub_id={bill['hub_source_id']} / action={action}")
    if action != "INSERTED":
        raise RuntimeError(f"{kind} 신규 등록 실패 또는 중복: action={action}. 새 case_id를 사용하세요.")


def send_real_stage(base, hub_source_id, stage, detected_value, field, extra=None):
    if not clean(detected_value):
        print(f"[SKIP] 실제 원천데이터에 없음: {stage}")
        return False
    alert = {
        **base,
        "hub_source_id": hub_source_id,
        "stage": stage,
        "changes": [{"field": field, "label": stage, "old": "", "new": clean(detected_value)}],
        **(extra or {}),
    }
    eligible = hub_notify.send_status_alerts([alert])
    if not eligible:
        raise RuntimeError(f"허브가 추적중단 처리함: {stage}. register 단계에서 O 판정했는지 확인하세요.")
    print(f"[PASS] 실제 감지 → 허브/Telegram: {stage} / {detected_value}")
    time.sleep(1)
    return True


def replay_common_lifecycle(session, bill, hub_source_id, include_committee=True):
    lifecycle = status_monitor.fetch_lifecycle(session, bill["bill_id"], bill) or {}
    if not lifecycle:
        raise RuntimeError(f"운영 lifecycle reader 결과 없음: {bill['bill_no']}")

    base = {
        **bill,
        "committee": lifecycle.get("committee") or bill.get("committee"),
        "detail_link": lifecycle.get("detail_link") or bill.get("detail_link"),
    }

    if include_committee:
        send_real_stage(base, hub_source_id, "소관위원회 회부", norm_date(lifecycle.get("committee_referral_date")), "committee_referral_date")
    send_real_stage(base, hub_source_id, "법제사법위원회 회부", norm_date(lifecycle.get("law_submit_date")), "law_submit_date")
    send_real_stage(base, hub_source_id, "본회의 처리", norm_date(lifecycle.get("plenary_date")), "plenary_date")

    post = post_plenary.fetch_post_plenary_status(bill, session=session) or {}
    send_real_stage(base, hub_source_id, "정부이송", clean(post.get("government_transfer_date")), "government_transfer_date")

    if post.get("promulgation_date") and post.get("promulgation_no"):
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
            raise RuntimeError(
                f"법제처 공포 교차검증 실패: {bill['bill_no']} / {post.get('promulgation_date')} / {post.get('promulgation_no')}"
            )
        verified["detail_link"] = verified.get("detail_link") or lem.public_law_link(verified)
        send_real_stage(
            base,
            hub_source_id,
            "공포",
            norm_date(verified.get("promulgation_date")),
            "promulgation_date",
            {
                "promulgation_date": norm_date(verified.get("promulgation_date")),
                "promulgation_no": clean(verified.get("promulgation_no")),
                "enforcement_date": norm_date(verified.get("enforcement_date")),
                "detail_link": verified.get("detail_link"),
            },
        )
        send_real_stage(
            base,
            hub_source_id,
            "시행",
            norm_date(verified.get("enforcement_date")),
            "enforcement_date",
            {
                "promulgation_date": norm_date(verified.get("promulgation_date")),
                "promulgation_no": clean(verified.get("promulgation_no")),
                "enforcement_date": norm_date(verified.get("enforcement_date")),
                "detail_link": verified.get("detail_link"),
            },
        )
    else:
        print(f"[SKIP] 실제 공포 데이터 없음: {bill['bill_no']}")

    return lifecycle


def replay_normal(session, case_id):
    bill = load_bill(session, NORMAL_BILL_NO)
    print(f"\n[NORMAL] 실제 의안 {bill['bill_no']} / {bill['bill_name']}")
    replay_common_lifecycle(session, bill, hub_id(case_id, "NORMAL"), include_committee=True)


def replay_alternative(session, case_id):
    original = load_bill(session, ALT_ORIGINAL_BILL_NO)
    source_id = hub_id(case_id, "ALT")
    print(f"\n[ALTERNATIVE] 실제 원의안 {original['bill_no']} / {original['bill_name']}")

    lifecycle = status_monitor.fetch_lifecycle(session, original["bill_id"], original) or {}
    if not lifecycle:
        raise RuntimeError("대안반영 원의안 lifecycle 조회 실패")

    base = {
        **original,
        "committee": lifecycle.get("committee") or original.get("committee"),
        "detail_link": lifecycle.get("detail_link") or original.get("detail_link"),
    }
    send_real_stage(base, source_id, "소관위원회 회부", norm_date(lifecycle.get("committee_referral_date")), "committee_referral_date")

    alt_result = clean(lifecycle.get("committee_process_result") or lifecycle.get("plenary_result"))
    if not is_alternative_reflection_result(alt_result):
        raise RuntimeError(f"실제 원천에서 대안반영폐기 확인 실패: {original['bill_no']} / {alt_result}")
    alt_date = norm_date(lifecycle.get("committee_process_date") or lifecycle.get("plenary_date")) or alt_result
    send_real_stage(base, source_id, "대안반영폐기", alt_date, "alternative_reflection", {"actualResult": alt_result})

    successor = find_verified_successor_bill(session, original, lifecycle)
    if not successor:
        raise RuntimeError(f"실제 후속대안 자동 식별 실패: {original['bill_no']}")
    successor_no = clean(successor.get("bill_no"))
    if successor_no != ALT_EXPECTED_SUCCESSOR_NO:
        raise RuntimeError(
            f"후속대안 오식별: original={ALT_ORIGINAL_BILL_NO} expected={ALT_EXPECTED_SUCCESSOR_NO} actual={successor_no}"
        )

    successor_bill = load_bill(session, successor_no)
    successor_base = {
        **successor_bill,
        "hub_source_id": source_id,
    }
    print(f"[PASS] 실제 대안관계 자동 식별: {ALT_ORIGINAL_BILL_NO} → {successor_no}")
    send_real_stage(
        successor_base,
        source_id,
        "위원회 대안 자동승계",
        successor_bill.get("proposal_date") or successor_no,
        "alternative_successor",
        {"predecessorBillNo": ALT_ORIGINAL_BILL_NO},
    )

    replay_common_lifecycle(session, successor_bill, source_id, include_committee=False)


def main():
    phase = clean(os.getenv("TEST_PHASE")).lower() or "register"
    case_id = clean(os.getenv("TEST_CASE_ID")) or datetime.now(monitor.KST).strftime("%Y%m%d%H%M")
    if not os.getenv("ASSEMBLY_API_KEY"):
        raise RuntimeError("ASSEMBLY_API_KEY secret is required")

    print(f"[INFO] historical hub real-data E2E / phase={phase} / case_id={case_id}")
    session = requests.Session()
    session.headers.update(monitor.HEADERS)
    try:
        if phase == "register":
            register_one(session, case_id, "NORMAL", NORMAL_BILL_NO)
            register_one(session, case_id, "ALT", ALT_ORIGINAL_BILL_NO)
            print("[NEXT] 허브 Telegram에서 NORMAL/ALT 두 건 모두 자사관련 O + 사유 입력 후 phase=continue 실행")
            return
        if phase == "continue":
            replay_normal(session, case_id)
            replay_alternative(session, case_id)
            print("\n[SUCCESS] historical real-data → 허브 → Spreadsheet/Telegram E2E 완료")
            print("[VERIFY] 기존 국회 알림방이 아니라 허브 알림방에만 메시지가 와야 합니다.")
            return
        raise ValueError("TEST_PHASE는 register 또는 continue여야 합니다.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
