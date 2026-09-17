import csv
import json
import re
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import monitor
import status_monitor
import content_enrichment

TARGET_LAWS = [
    "식품 등의 표시·광고에 관한 법률",
    "표시·광고의 공정화에 관한 법률",
    "가맹사업거래의 공정화에 관한 법률",
    "식품위생법",
    "건강기능식품에 관한 법률",
    "자원의 절약과 재활용촉진에 관한 법률",
]
START = date(2026, 1, 1)
END = date.today()
OUT_CSV = Path("audit_final_fast_2026_six_laws.csv")
OUT_JSON = Path("audit_final_fast_2026_six_laws.json")

OFFICIAL_ONLY = [
    {
        "bill_id": "",
        "bill_no": "2217933",
        "bill_name": "식품 등의 표시ㆍ광고에 관한 법률 일부개정법률안(대안)",
        "proposal_date": "2026-03-30",
        "proposer": "보건복지위원장",
        "proposer_kind": "위원회안",
        "committee": "보건복지위원회",
        "process_result": "원안가결",
        "detail_link": "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out/2217933/detailRP",
        "source": "국회입법현황",
        "matched_law": "식품 등의 표시·광고에 관한 법률",
    },
    {
        "bill_id": "",
        "bill_no": "2221426",
        "bill_name": "표시·광고의 공정화에 관한 법률 일부개정법률안",
        "proposal_date": "2026-09-17",
        "proposer": "",
        "proposer_kind": "의원발의",
        "committee": "",
        "process_result": "",
        "detail_link": "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out/2221426/detailRP",
        "source": "국회입법현황",
        "matched_law": "표시·광고의 공정화에 관한 법률",
    },
]


def clean(v):
    return str(v or "").strip()


def norm_date(v):
    d = monitor.parse_date(v)
    return d.isoformat() if d else clean(v)


def representative(v):
    s = clean(v)
    m = re.match(r"([가-힣A-Za-z·ㆍ]+)의원", s)
    return m.group(1) if m else s


def snapshot_from_member(row):
    return {
        "committee": clean(row.get("COMMITTEE")),
        "committee_referral_date": clean(row.get("COMMITTEE_DT")),
        "committee_present_date": clean(row.get("CMT_PRESENT_DT")),
        "committee_process_date": clean(row.get("CMT_PROC_DT")),
        "committee_process_result": clean(row.get("CMT_PROC_RESULT_CD")),
        "law_submit_date": clean(row.get("LAW_SUBMIT_DT")),
        "law_present_date": clean(row.get("LAW_PRESENT_DT")),
        "law_process_date": clean(row.get("LAW_PROC_DT")),
        "law_process_result": clean(row.get("LAW_PROC_RESULT_CD")),
        "plenary_date": clean(row.get("PROC_DT")),
        "plenary_result": clean(row.get("PROC_RESULT")),
    }


def hub_stage(bill, snapshot):
    result = clean(bill.get("process_result")) or clean(snapshot.get("plenary_result"))
    if "대안반영폐기" in result:
        return "대안반영폐기"
    if "철회" in result:
        return "철회"
    if bill.get("bill_no") == "2217933":
        return "공포"
    return status_monitor.highest_stage(snapshot)


def extract_official_basic(session, bill):
    url = f"https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out/{bill['bill_no']}/detailRP"
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or r.encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        text = " ".join(soup.stripped_strings)
        m = re.search(r"발의정보\s+\|?\s*([가-힣A-Za-z·ㆍ]+의원(?:\s+등\s+\d+인)?|[가-힣A-Za-z·ㆍ]+위원장)", text)
        if not m:
            m = re.search(r"([가-힣A-Za-z·ㆍ]+의원\s+등\s+\d+인|[가-힣A-Za-z·ㆍ]+위원장)\s*,?\s*제\s*" + re.escape(bill['bill_no']) + r"호", text)
        proposer = m.group(1) if m else ""
        return proposer
    except Exception:
        return ""


def summarize_main(text):
    points = content_enrichment.main_content_points(text)
    if not points:
        return ""
    vals = [content_enrichment.clean_inline(p) for p in points if content_enrichment.clean_inline(p)]
    return " / ".join(f"{i+1}. {p}" for i, p in enumerate(vals)) if len(vals) > 1 else (vals[0] if vals else "")


def main():
    s = requests.Session()
    s.headers.update(monitor.HEADERS)
    try:
        member_bills = monitor.fetch_recent_member_bills(s, START)
        bills = []
        for b in member_bills:
            law = monitor.match_watched_law(clean(b.get("bill_name")))
            d = monitor.parse_date(b.get("proposal_date"))
            if law in TARGET_LAWS and d and START <= d <= END:
                bills.append({**b, "matched_law": law})
        bills.extend(OFFICIAL_ONLY)

        uniq = {clean(b.get("bill_no")): b for b in bills if clean(b.get("bill_no"))}
        bills = list(uniq.values())
        rows = []

        for i, b in enumerate(sorted(bills, key=lambda x: (TARGET_LAWS.index(x["matched_law"]), norm_date(x.get("proposal_date")), clean(x.get("bill_no")))), 1):
            print(f"[{i}/{len(bills)}] {b['bill_no']}")
            content = content_enrichment.fetch_bill_content(b, session=s)
            reason = content_enrichment.summarize_reason(content.get("proposal_reason") or "", max_chars=900)
            main_content = summarize_main(content.get("main_content") or "")

            snapshot = {}
            if clean(b.get("bill_id")):
                full = status_monitor.fetch_matching_row(s, monitor.MEMBER_BILLS_API, b, include_age=True) or {}
                snapshot = snapshot_from_member(full)
            elif b.get("bill_no") == "2217933":
                snapshot = {"plenary_date": "2026-04-23", "plenary_result": "원안가결"}

            prop = clean(b.get("proposer"))
            if not prop:
                prop = extract_official_basic(s, b)

            rows.append({
                "법률명": b["matched_law"],
                "의안번호": clean(b.get("bill_no")),
                "법률안명": clean(b.get("bill_name")),
                "대표발의자": representative(prop or b.get("proposer_kind")),
                "발의일": norm_date(b.get("proposal_date")),
                "현재단계": hub_stage(b, snapshot),
                "제안이유": reason,
                "주요내용": main_content,
                "원문링크": f"https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out/{b.get('bill_no')}/detailRP",
                "처리결과_API": clean(b.get("process_result")) or clean(snapshot.get("plenary_result")),
                "내용출처": clean(content.get("content_source")),
                "내용수집오류": clean(content.get("content_error")),
            })

        counts = {law: sum(1 for r in rows if r["법률명"] == law) for law in TARGET_LAWS}
        stage_counts = {}
        for r in rows:
            stage_counts[r["현재단계"]] = stage_counts.get(r["현재단계"], 0) + 1
        empty = [r["의안번호"] for r in rows if not r["제안이유"] and not r["주요내용"]]

        OUT_JSON.write_text(json.dumps({"total": len(rows), "counts": counts, "stage_counts": stage_counts, "content_empty": empty, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        print(json.dumps({"total": len(rows), "counts": counts, "stage_counts": stage_counts, "content_empty": empty}, ensure_ascii=False, indent=2))
    finally:
        s.close()


if __name__ == "__main__":
    main()
