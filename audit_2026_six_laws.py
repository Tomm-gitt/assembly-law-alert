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


def law_variants(law):
    return list(dict.fromkeys([
        law,
        law.replace("·", "ㆍ"),
        law.replace("ㆍ", "·"),
    ]))


def fetch_receipts_by_law(session):
    """Direct BILLRCP queries per target law so committee/government bills are not lost by global paging/order."""
    found = {}
    for law in TARGET_LAWS:
        for query in law_variants(law):
            for page in range(1, 6):
                data = monitor.request_api(
                    session,
                    monitor.RECEIPT_API,
                    {
                        "pIndex": str(page),
                        "pSize": "1000",
                        "BILL_NM": query,
                    },
                )
                rows = monitor.parse_rows(data, monitor.RECEIPT_API)
                if not rows:
                    break
                for row in rows:
                    if str(row.get("ERACO") or "").strip() != monitor.ERACO:
                        continue
                    if "법률안" not in str(row.get("BILL_KIND") or ""):
                        continue
                    proposal_date = monitor.parse_date(row.get("PPSL_DT"))
                    if not proposal_date or proposal_date < CUTOFF:
                        continue
                    bill_name = str(row.get("BILL_NM") or "")
                    matched = monitor.match_watched_law(bill_name)
                    if matched != law:
                        continue
                    bill_id = str(row.get("BILL_ID") or "").strip()
                    if not bill_id:
                        continue
                    found[bill_id] = {
                        "bill_id": row.get("BILL_ID"),
                        "bill_no": row.get("BILL_NO"),
                        "bill_name": row.get("BILL_NM"),
                        "proposal_date": row.get("PPSL_DT"),
                        "proposer": None,
                        "proposer_kind": row.get("PPSR_KIND") or "제안자 정보 없음",
                        "committee": None,
                        "process_result": row.get("PROC_RSLT"),
                        "detail_link": row.get("LINK_URL"),
                        "source": monitor.RECEIPT_API,
                    }
                if len(rows) < 1000:
                    break
    return list(found.values())


def main():
    session = requests.Session()
    session.headers.update(monitor.HEADERS)
    try:
        member = monitor.fetch_recent_member_bills(session, CUTOFF)
        receipts_global = monitor.fetch_recent_receipts(session, CUTOFF)
        receipts_direct = fetch_receipts_by_law(session)
        merged = monitor.merge_by_bill_id(member, receipts_global, receipts_direct)

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
            "receipt_global_raw_count": len(receipts_global),
            "receipt_direct_raw_count": len(receipts_direct),
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

        print(json.dumps({
            "target_total": len(rows),
            "counts": counts,
            "receipt_direct_raw_count": len(receipts_direct),
        }, ensure_ascii=False, indent=2))
        for r in rows:
            print(f"{r['law']} | {r.get('bill_no')} | {r.get('proposal_date')} | {r.get('bill_name')} | {r.get('proposer') or r.get('proposer_kind')} | {r.get('process_result')}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
