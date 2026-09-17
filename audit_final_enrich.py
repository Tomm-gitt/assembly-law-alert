import csv
import json
import re
from datetime import date
from pathlib import Path

import requests

import monitor
import status_monitor
import content_enrichment
import post_plenary

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


def hub_stage_from(bill, snap, post):
    """HUB의 currentStage 표현으로만 반환한다."""
    result = str(bill.get("process_result") or "").strip()

    if "대안반영폐기" in result:
        return "대안반영폐기"
    if "철회" in result:
        return "철회"
    if result == "부결":
        return "본회의 처리"

    if str(post.get("promulgation_date") or "").strip():
        return "공포"
    if str(post.get("government_transfer_date") or "").strip():
        return "정부이송"

    return status_monitor.highest_stage(snap)


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

        # Open API에 아직 없지만 공식 국회입법현황에서 확인된 의안들을 합산한다.
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
        bills.append({
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
                snap = {"plenary_date": "2026-04-23", "plenary_result": "원안가결"}
            else:
                snap = status_monitor.fetch_lifecycle(s, str(b.get("bill_id") or ""), b)

            post = post_plenary.fetch_post_plenary_status(b, session=s)
            stage = hub_stage_from(b, snap, post)

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
                "정부이송일": str(post.get("government_transfer_date") or ""),
                "공포일": str(post.get("promulgation_date") or ""),
                "공포번호": str(post.get("promulgation_no") or ""),
                "내용출처": content.get("content_source") or "",
                "내용수집오류": content.get("content_error") or "",
            })

        OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
            w.writeheader(); w.writerows(out)
        counts = {law: sum(1 for r in out if r["법률명"] == law) for law in TARGET_LAWS}
        errors = [r["의안번호"] for r in out if not r["제안이유"] and not r["주요내용"]]
        stage_counts = {}
        for r in out:
            stage_counts[r["현재단계"]] = stage_counts.get(r["현재단계"], 0) + 1
        print(json.dumps({"total":len(out),"counts":counts,"stage_counts":stage_counts,"content_empty":errors},ensure_ascii=False,indent=2))
    finally:
        s.close()

if __name__ == "__main__":
    main()
