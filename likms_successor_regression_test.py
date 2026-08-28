import os

import requests

import monitor
import status_monitor
from alternative_successor import is_alternative_reflection_result
from successor_resolution import find_verified_successor_bill

CASES = {
    "2210213": "2216767",
    "2209981": "2214610",
}


def clean(value):
    return status_monitor.clean(value)


def load_origin(session, bill_no):
    member = status_monitor.fetch_matching_row(
        session,
        monitor.MEMBER_BILLS_API,
        {"bill_no": bill_no},
        include_age=True,
    )
    if not member:
        raise RuntimeError(f"원의안 조회 실패: {bill_no}")

    bill_id = clean(member.get("BILL_ID"))
    bill_name = clean(member.get("BILL_NAME"))
    law_name = monitor.match_watched_law(bill_name)
    if not bill_id or not law_name:
        raise RuntimeError(f"원의안 식별 실패: {bill_no} / {bill_name}")

    entry = {
        "bill_id": bill_id,
        "bill_no": bill_no,
        "bill_name": bill_name,
        "matched_law": law_name,
        "proposal_date": clean(member.get("PROPOSE_DT")),
        "status_tracking": True,
    }
    lifecycle = status_monitor.fetch_lifecycle(session, bill_id, entry) or {}
    if not (
        is_alternative_reflection_result(lifecycle.get("committee_process_result"))
        or is_alternative_reflection_result(lifecycle.get("plenary_result"))
    ):
        raise RuntimeError(f"대안반영폐기 확인 실패: {bill_no}")
    return entry, lifecycle


def run_case(session, original_no, expected_no=None):
    suffix = f" / expected={expected_no}" if expected_no else " / custom dry-run"
    print(f"\n[CASE] {original_no}{suffix}")
    entry, lifecycle = load_origin(session, original_no)
    print(
        f"[PASS] 원의안: {original_no} / {entry['matched_law']} / "
        f"{lifecycle.get('committee_process_date')}"
    )

    successor = find_verified_successor_bill(session, entry, lifecycle)
    if not successor:
        raise RuntimeError(f"LIKMS 공식관계 후속대안 미확정: {original_no}")

    actual_no = clean(successor.get("bill_no"))
    if expected_no and actual_no != expected_no:
        raise RuntimeError(
            f"후속 대안 오도출: {original_no} / expected={expected_no} / actual={actual_no}"
        )

    label = "회귀검증" if expected_no else "임의 의안 DRY-RUN"
    print(
        f"[SUCCESS] LIKMS 대안정보 {label}: {original_no} -> {actual_no} / "
        f"{successor.get('bill_name')}"
    )
    if not expected_no:
        print("[INFO] DRY-RUN: seen_bills.json은 수정하지 않았습니다.")


def main():
    if not os.getenv("ASSEMBLY_API_KEY"):
        raise RuntimeError("ASSEMBLY_API_KEY secret is required")

    custom_original_no = clean(os.getenv("TEST_ORIGINAL_BILL_NO"))

    session = requests.Session()
    session.headers.update(monitor.HEADERS)
    try:
        if custom_original_no:
            run_case(session, custom_original_no)
            return

        for original_no, expected_no in CASES.items():
            run_case(session, original_no, expected_no)
    finally:
        session.close()


if __name__ == "__main__":
    main()
