import json
from datetime import datetime
import requests
import monitor
import status_monitor
import status_alert_runner

SEED_FILE = "historical_tracking_seed_20261021.json"
STOP_BILL_NOS = ["2221089","2221375","2221534","2221749","2221860","2221913","2221598","2221911","2220991","2221340","2221536","2221754","2221939","2221152","2221426","2221601","2221076"]
BASELINE_TAG = "HISTORICAL_O_BASELINE_20261021"

def clean(v):
    return str(v or "").strip()

def main():
    seen = monitor.load_seen()
    with open(SEED_FILE, encoding="utf-8") as f:
        seed = json.load(f)["bills"]

    # HUB에서 X 또는 종결로 확정된 현재 추적 건은 즉시 중단.
    stopped = []
    for bill_id, entry in seen.items():
        if clean(entry.get("bill_no")) in STOP_BILL_NOS:
            entry["status_tracking"] = False
            entry.pop("hub_lifecycle_outbox", None)
            entry["tracking_excluded_reason"] = "HUB_X_OR_TERMINAL_20261021"
            stopped.append(clean(entry.get("bill_no")))

    session = requests.Session()
    session.headers.update(monitor.HEADERS)
    now = datetime.now(monitor.KST).isoformat(timespec="seconds")
    added, refreshed, failed = [], [], []

    try:
        for item in seed:
            bill_id = clean(item.get("bill_id"))
            bill_no = clean(item.get("bill_no"))
            if not bill_id or not bill_no:
                failed.append({"bill_no": bill_no, "error": "MISSING_ID"})
                continue

            existing = seen.get(bill_id)
            entry = dict(existing or {})
            entry.update({
                "bill_name": clean(item.get("bill_name")),
                "bill_no": bill_no,
                "matched_law": clean(item.get("matched_law")),
                "proposal_date": clean(item.get("proposal_date")),
                "proposer": clean(item.get("proposer")),
                "status_tracking": True,
                "historical_baseline": BASELINE_TAG,
            })
            entry.pop("tracking_excluded_reason", None)
            entry.setdefault("hub_lifecycle_outbox", {})
            entry.setdefault("hub_lifecycle_receipts", {})

            try:
                current_raw = status_monitor.fetch_lifecycle(session, bill_id, entry)
                if not current_raw:
                    raise RuntimeError("CURRENT_LIFECYCLE_EMPTY")
                entry["lifecycle"] = status_monitor.merge_snapshot({}, current_raw)
                entry["last_status_checked_at"] = now
                entry["lifecycle_initialized_at"] = entry.get("lifecycle_initialized_at") or now
                entry["historical_baseline_initialized_at"] = now
                seen[bill_id] = entry
                (refreshed if existing else added).append(bill_no)
                print(f"[INFO] historical O tracking baseline initialized: {bill_no} / {status_monitor.highest_stage(entry['lifecycle'])}")
            except Exception as exc:
                failed.append({"bill_no": bill_no, "error": str(exc)[:300]})
                print(f"[ERROR] historical O baseline failed: {bill_no} / {exc}")

        monitor.save_seen(seen)
    finally:
        session.close()

    print(json.dumps({
        "added": len(added),
        "refreshed": len(refreshed),
        "stopped": len(stopped),
        "failed": failed,
        "added_bill_nos": added,
        "stopped_bill_nos": stopped,
    }, ensure_ascii=False, indent=2))

    if failed:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
