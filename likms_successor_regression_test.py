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


def _exact_origin_row(session, bill_no):
    lookup = {"bill_no": bill_no}

    # 1) 의원발의 API: 기존 회귀사례의 가장 안정적인 경로
    try:
        row = status_monitor.fetch_matching_row(
            session,
            monitor.MEMBER_BILLS_API,
            lookup,
            include_age=True,
        )
        if row and clean(row.get("BILL_NO")) == bill_no:
            print(f"[INFO] 원의안 조회 경로: MEMBER_BILLS_API / {bill_no}")
            return row
    except Exception as exc:
        print(f"[WARN] 의원발의 API 원의안 조회 실패: {bill_no} / {exc}")

    # 2) 처리의안 API: 정부안/위원회안 등 의원발의 API 밖의 의안을 보완
    try:
        row = status_monitor.fetch_matching_row(
            session,
            status_monitor.PROCESSED_API,
            lookup,
            include_age=True,
        )
        if row and clean(row.get("BILL_NO")) == bill_no:
            print(f"[INFO] 원의안 조회 경로: PROCESSED_API / {bill_no}")
            return row
    except Exception as exc:
        print(f"[WARN] 처리의안 API 원의안 조회 실패: {bill_no} / {exc}")

    # 3) 접수의안 API: 최종 fallback. 반드시 exact BILL_NO만 허용한다.
    try:
        data = monitor.request_api(
            session,
            monitor.RECEIPT_API,
            {"pIndex": "1", "pSize": "100", "BILL_NO": bill_no},
        )
        rows = monitor.parse_rows(data, monitor.RECEIPT_API)
        for row in rows:
            if clean(row.get("BILL_NO")) == bill_no:
                print(f"[INFO] 원의안 조회 경로: RECEIPT_API / {bill_no}")
                return row
    except Exception as exc:
        print(f"[WARN] 접수의안 API 원의안 조회 실패: {bill_no} / {exc}")

    return None


def load_origin(session, bill_no):
    origin = _exact_origin_row(session, bill_no)
    if not origin:
        raise RuntimeError(f"원의안 조회 실패: {bill_no}")

    bill_id = clean(origin.get("BILL_ID"))
    bill_name = clean(origin.get("BILL_NAME") or origin.get("BILL_NM"))
    law_name = monitor.match_watched_law(bill_name)
    if not bill_id or not law_name:
        raise RuntimeError(f"원의안 식별 실패: {bill_no} / {bill_name}")

    entry = {
        "bill_id": bill_id,
        "bill_no": bill_no,
        "bill_name": bill_name,
        "matched_law": law_name,
        "proposal_date": clean(origin.get("PROPOSE_DT") or origin.get("PPSL_DT")),
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
