import csv
import json
import re
from datetime import date
from pathlib import Path

import requests

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
START = date(2026,1,1)
END = date.today()
OUT_CSV = Path("audit_final_2026_six_laws.csv")
OUT_JSON = Path("audit_final_2026_six_laws.json")


def rep_name(v):
    s = str(v or "").strip()
    if not s:
        return ""
    m = re.match(r"\s*([가-힣A-Za-z·ㆍ]+)의원", s)
    return m.group(1) if m else s


def norm_date(v):
    d = monitor.parse_date(v)
    return d.isoformat() if d else str(v or "")


def summarize_main(text):
    pts = content_enrichment.main_content_points(text)
    if not pts:
        return ""
    cleaned = []
    for p in pts:
        p = content_enrichment.clean_inline(p)
        if len(p) > 420:
            p = p[:417].rstrip() + "..."
        cleaned.append(p)
    if len(cleaned) == 1:
        return cleaned[0]
    return " / ".join(f"{i+1}. {p}" for i,p in enumerate(cleaned))


def stage_from(bill, snap):
    result = str(bill.get("process_result") or "").strip()
    if result:
        return result
    stage = status_monitor.highest_stage(snap)
    if stage == "소관위원회 처리" and snap.get("committee_process_result"):
        return f"소관위원회 처리({snap.get('committee_process_result')})"
    if stage == "법제사법위원회 처리" and snap.get("law_process_result"):
        return f"법제사법위원회 처리({snap.get('law_process_result')})"
    if stage == "본회의 처리" and snap.get("plenary_result"):
        return f"본회의 처리({snap.get('plenary_result')})"
    return stage


def main():
    s = requests.Session()
    s.headers.update(monitor.HEADERS)
    try:
        member = monitor.fetch_recent_member_bills(s, START)
        bills = []
        for b in member:
            law = monitor.match_watched_law(str(b.get("bill_name") or ""))
            d = monitor.parse_date(b.get("proposal_date"))
            if law in TARGET_LAWS and d and START <= d <= END:
                bills.append({**b, "matched_law": law})

        # 2026년 기간 중 확인된 위원회 대안. 의원발의 API에는 존재하지 않으므로 별도 합산.
        bills.append({
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
        })

        uniq = {}
        for b in bills:
            uniq[str(b.get("bill_no"))] = b
        bills = list(uniq.values())

        out = []
        for i,b in enumerate(sorted(bills, key=lambda x:(TARGET_LAWS.index(x["matched_law"]), norm_date(x.get("proposal_date")), str(x.get("bill_no")))),1):
            print(f"[{i}/{len(bills)}] {b['bill_no']} {b['bill_name']}")
            content = content_enrichment.fetch_bill_content(b, session=s)
            reason = content_enrichment.summarize_reason(content.get("proposal_reason") or "", max_chars=700)
            main_text = summarize_main(content.get("main_content") or "")

            if b.get("bill_no") == "2217933":
                stage = "공포(2026-05-26, 법률 제21707호)"
            else:
                snap = status_monitor.fetch_lifecycle(s, str(b.get("bill_id") or ""), b)
                stage = stage_from(b, snap)

            out.append({
                "법률명": b["matched_law"],
                "의안번호": str(b.get("bill_no") or ""),
                "법률안명": str(b.get("bill_name") or ""),
                "대표발의자": rep_name(b.get("proposer") or b.get("proposer_kind")),
                "발의일": norm_date(b.get("proposal_date")),
                "현재단계": stage,
                "제안이유": reason,
                "주요내용": main_text,
                "원문링크": f"https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out/{b.get('bill_no')}/detailRP",
                "처리결과_API": str(b.get("process_result") or ""),
                "내용출처": content.get("content_source") or "",
                "내용수집오류": content.get("content_error") or "",
            })

        OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
            w.writeheader(); w.writerows(out)
        counts = {law: sum(1 for r in out if r["법률명"] == law) for law in TARGET_LAWS}
        errors = [r["의안번호"] for r in out if not r["제안이유"] and not r["주요내용"]]
        print(json.dumps({"total":len(out),"counts":counts,"content_empty":errors},ensure_ascii=False,indent=2))
    finally:
        s.close()

if __name__ == "__main__":
    main()
