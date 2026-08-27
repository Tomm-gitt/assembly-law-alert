import requests

import alternative_successor
import monitor


def main():
    original_entry = {
        "bill_no": "2210213",
        "bill_name": "소비자기본법 일부개정법률안",
        "matched_law": "소비자기본법",
        "proposal_date": "2025-04-29",
        "status_tracking": True,
    }
    lifecycle = {
        "committee_process_date": "2025-12-17",
        "committee_process_result": "대안반영폐기",
    }

    session = requests.Session()
    session.headers.update(monitor.HEADERS)
    try:
        successor = alternative_successor.find_successor_bill(session, original_entry, lifecycle)
    finally:
        session.close()

    if not successor:
        raise RuntimeError("위원회 대안 자동승계 후보를 찾지 못했습니다.")

    expected = "2216767"
    actual = str(successor.get("bill_no") or "")
    print("[INFO] 원 의안: 2210213 소비자기본법 일부개정법률안")
    print("[INFO] 대안반영폐기: 2025-12-17")
    print(f"[INFO] 자동 탐색 후속 대안: {actual} {successor.get('bill_name')}")

    if actual != expected:
        raise RuntimeError(f"후속 대안 오연결: expected={expected}, actual={actual}, row={successor}")

    if "대안" not in str(successor.get("bill_name") or ""):
        raise RuntimeError(f"후속 의안이 대안 의안이 아닙니다: {successor}")

    print("[PASS] 대안반영폐기 → 위원회 대안 자동승계 실데이터 테스트 성공")


if __name__ == "__main__":
    main()
