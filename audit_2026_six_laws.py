import csv
import json
from datetime import date
from pathlib import Path

import requests

import monitor

TARGET_LAWS = [
    "식품 등의 표시·광고에 관한 법률",
    "표시·광고의 공정화에 관한 법률",
    "가맹사업거래의 공정화에 관한 법률",
    "식품위생법",
    "건강기능식품에 관한 법률",
    "자원의 절약과 재활용촉진에 관한 법률",
]
CUTOFF = date(2026, 1, 1)
OUT_JSON = Path("audit_2026_six_laws.json")
OUT_CSV = Path("audit_2026_six_laws.csv")


def main():
    session = requests.Session()
    session.headers.update(monitor.HEADERS)
    try:
        member = monitor.fetch_recent_member_bills(session, CUTOFF)
        receipts = monitor.fetch_recent_receipts(session, CUTOFF)
        merged = monitor.merge_by_bill_id(member, receipts)

        rows = []
        for bill in merged:
            law = monitor.match_watched_law(str(bill.get("bill_name") or ""))
            if law not in TARGET_LAWS:
                continue
            proposal_date = monitor.parse_date(bill.get("proposal_date"))
            if not proposal_date or proposal_date < CUTOFF:
                continue
            rows.append({
                "law": law,
                "bill_id": bill.get("bill_id"),
                "bill_no": bill.get("bill_no"),
                "bill_name": bill.get("bill_name"),
                "proposal_date": bill.get("proposal_date"),
                "proposer": bill.get("proposer"),
                "proposer_kind": bill.get("proposer_kind"),
                "committee": bill.get("committee"),
                "process_result": bill.get("process_result"),
                "detail_link": bill.get("detail_link"),
                "source": bill.get("source"),
            })

        rows.sort(key=lambda x: (TARGET_LAWS.index(x["law"]), str(x.get("proposal_date") or ""), str(x.get("bill_no") or "")))
        counts = {law: sum(1 for r in rows if r["law"] == law) for law in TARGET_LAWS}
        payload = {
            "cutoff": CUTOFF.isoformat(),
            "member_raw_count": len(member),
            "receipt_raw_count": len(receipts),
            "merged_raw_count": len(merged),
            "target_total": len(rows),
            "counts": counts,
            "rows": rows,
        }
        OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["law"])
            writer.writeheader()
            writer.writerows(rows)

        print(json.dumps({"target_total": len(rows), "counts": counts}, ensure_ascii=False, indent=2))
        for r in rows:
            print(f"{r['law']} | {r.get('bill_no')} | {r.get('proposal_date')} | {r.get('bill_name')} | {r.get('proposer') or r.get('proposer_kind')} | {r.get('process_result')}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
