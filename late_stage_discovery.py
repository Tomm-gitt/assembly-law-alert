import json
from datetime import datetime, timedelta
from pathlib import Path

import requests

import monitor
from post_plenary import fetch_post_plenary_status

PROCESSED_API = "nzpltgfqabtcpsmai"
STATE_PATH = Path("late_stage_discovery_state.json")
MAX_PAGES = 5
PAGE_SIZE = 1000
LOOKBACK_DAYS = 120


def load_state():
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iso_date(value: str) -> str:
    parsed = monitor.parse_date(value)
    return parsed.isoformat() if parsed else ""


def fetch_candidates(session, cutoff):
    results = []
    for page in range(1, MAX_PAGES + 1):
        data = monitor.request_api(session, PROCESSED_API, {"pIndex": str(page), "pSize": str(PAGE_SIZE), "AGE": monitor.AGE})
        rows = monitor.parse_rows(data, PROCESSED_API)
        if not rows:
            break
        page_dates = []
        for row in rows:
            proc_dt = monitor.parse_date(row.get("PROC_DT"))
            if proc_dt:
                page_dates.append(proc_dt)
            if not proc_dt or proc_dt < cutoff:
                continue
            bill_name = str(row.get("BILL_NAME") or "").strip()
            matched = monitor.match_watched_law(bill_name)
            if not matched:
                continue
            results.append({
                "bill_id": row.get("BILL_ID"),
                "bill_no": row.get("BILL_NO"),
                "bill_name": bill_name,
                "proposal_date": row.get("PROPOSE_DT"),
                "matched_law": matched,
                "detail_link": row.get("LINK_URL"),
                "process_result": row.get("PROC_RESULT_CD"),
            })
        if page_dates and max(page_dates) < cutoff:
            break
        if len(rows) < PAGE_SIZE:
            break
    return results


def main():
    state = load_state()
    today = datetime.now(monitor.KST).date()
    if not state:
        save_state({"started_date": today.isoformat()})
        print(f"[INFO] 과거 의안 후속단계 감지 기준일 설정: {today.isoformat()}")
        return 0

    started_date = datetime.strptime(state["started_date"], "%Y-%m-%d").date()
    cutoff = today - timedelta(days=LOOKBACK_DAYS)
    seen = monitor.load_seen()
    session = requests.Session()
    session.headers.update(monitor.HEADERS)
    imported = 0
    try:
        for bill in fetch_candidates(session, cutoff):
            bill_id = str(bill.get("bill_id") or "").strip()
            if not bill_id or bill_id in seen:
                continue
            post = fetch_post_plenary_status(bill, session=session)
            transfer = post.get("government_transfer_date") or ""
            promulgation = post.get("promulgation_date") or ""
            event = ""
            if promulgation and promulgation >= started_date.isoformat():
                event = "공포"
            elif transfer and transfer >= started_date.isoformat():
                event = "정부이송"
            if not event:
                continue
            now = datetime.now(monitor.KST).isoformat(timespec="seconds")
            seen[bill_id] = {
                "bill_no": bill.get("bill_no"),
                "bill_name": bill.get("bill_name"),
                "proposal_date": bill.get("proposal_date"),
                "matched_law": bill.get("matched_law"),
                "first_seen_at": now,
                "status_tracking": True,
                "auto_imported_late_stage": True,
                "late_stage_discovered_event": event,
                "late_stage_discovered_at": now,
            }
            imported += 1
            print(f"[INFO] 과거 의안 자동 편입: {bill.get('bill_no')} / {event}")
        monitor.save_seen(seen)
        print(f"[INFO] 과거 의안 후속단계 신규 편입: {imported}건")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
