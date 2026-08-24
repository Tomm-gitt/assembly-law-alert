import json
import os
import sys
from datetime import datetime
from pathlib import Path

STATE_PATH = Path("seen_bills.json")


def load_seen():
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_seen(seen):
    STATE_PATH.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def normalize_action(value: str) -> bool:
    value = (value or "").strip().lower()
    if value == "exclude":
        return False
    if value == "resume":
        return True
    raise ValueError(f"지원하지 않는 동작입니다: {value}")


def main() -> int:
    bill_no = (os.getenv("BILL_NO") or "").strip()
    action = os.getenv("TRACKING_ACTION") or ""

    if not bill_no:
        raise ValueError("의안번호가 비어 있습니다.")

    enabled = normalize_action(action)
    seen = load_seen()

    matched_id = None
    matched_entry = None
    for bill_id, entry in seen.items():
        if str(entry.get("bill_no") or "").strip() == bill_no:
            matched_id = bill_id
            matched_entry = entry
            break

    if matched_entry is None:
        raise ValueError(
            f"seen_bills.json에서 의안번호 {bill_no}를 찾지 못했습니다. "
            "신규 의안 모니터에 먼저 감지된 의안인지 확인하세요."
        )

    matched_entry["status_tracking"] = enabled
    matched_entry["status_tracking_updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    save_seen(seen)

    status = "재개" if enabled else "제외"
    print(f"[INFO] 상태추적 {status} 완료")
    print(f"[INFO] 의안번호: {bill_no}")
    print(f"[INFO] 법률안명: {matched_entry.get('bill_name') or '-'}")
    print(f"[INFO] BILL_ID: {matched_id}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
