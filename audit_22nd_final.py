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
import alternative_successor
import audit_official_crosscheck as official_source

TARGET_LAWS = official_source.TARGET_LAWS
START = date(2024, 5, 30)
END = date.today()
OUT_CSV = Path("audit_22nd_final_six_laws.csv")
OUT_JSON = Path("audit_22nd_final_six_laws.json")

def clean(v):
    return str(v or "").strip()

def norm_date(v):
    d = monitor.parse_date(v)
    return d.isoformat() if d else clean(v)

def representative(v):
    s = re.sub(r"\s+", " ", clean(v))
    # 공식 페이지 전후 라벨 제거
    s = re.sub(r"^(?:제안이유 및 주요내용\s*)?(?:정보제공\s*)?(?:발의정보\s*)?", "", s).strip()
    m = re.search(r"([가-힣A-Za-z·ㆍ]+)\s*의원", s)
    if m:
        return m.group(1)
    m = re.search(r"([가-힣A-Za-z·ㆍ]+위원장)", s)
    if m:
        return m.group(1)
    return s

def summarize_main(text):
    pts = content_enrichment.main_content_points(text)
    vals = [content_enrichment.clean_inline(p) for p in pts if content_enrichment.clean_inline(p)]
    if not vals:
        return ""
    return " / ".join(f"{i+1}. {p}" for i,p in enumerate(vals)) if len(vals) > 1 else vals[0]

def receipt_row(session, bill_no):
    try:
        data = monitor.request_api(session, monitor.RECEIPT_API, {
            "pIndex": "1", "pSize": "100", "BILL_NO": bill_no
        })
        rows = monitor.parse_rows(data, monitor.RECEIPT_API)
    except Exception:
        return {}
    for row in rows:
        if clean(row.get("BILL_NO")) == bill_no:
            return row
    return {}

def member_row(session, bill):
    try:
        return status_monitor.fetch_matching_row(
            session, monitor.MEMBER_BILLS_API,
            {"bill_no": bill["bill_no"], "bill_name": bill["bill_name"], "bill_id": ""},
            include_age=True,
        ) or {}
    except Exception:
        return {}

def lifecycle_for(session, bill, member):
    if member:
        entry = {
            "bill_id": clean(member.get("BILL_ID")),
            "bill_no": bill["bill_no"],
            "bill_name": bill["bill_name"],
        }
        try:
            return status_monitor.fetch_lifecycle(session, entry["bill_id"], entry) or {}
        except Exception as e:
            print(f"WARN lifecycle {bill['bill_no']}: {e}")
    return {}

def hub_stage(bill, lifecycle, post):
    result = clean(bill.get("status_hint")) or clean(lifecycle.get("plenary_result"))
    if "대안반영폐기" in result:
        return "대안반영폐기"
    if "철회" in result:
        return "철회"
    if result in ("폐기", "부결"):
        return result
    if clean(post.get("promulgation_date")):
        return "공포"
    if clean(post.get("government_transfer_date")):
        return "정부이송"
    stage = status_monitor.highest_stage(lifecycle)
    if stage and stage != "발의/접수":
        return stage
    # 공식목록에서 가결이 확인됐지만 API lifecycle을 못 얻은 경우
    if result in ("원안가결", "수정가결"):
        return "본회의 처리"
    return "발의/접수"

def build_official_universe(session):
    snapshot = Path("audit_official_crosscheck.json")
    if snapshot.exists():
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        rows = data.get("official_rows") or []
        print(f"OFFICIAL SNAPSHOT: {len(rows)}")
        return rows

    rows = {}
    for law in TARGET_LAWS:
        items = official_source.collect_official(session, law)
        print(f"OFFICIAL {law}: {len(items)}")
        for x in items:
            rows[x["bill_no"]] = x
    return list(rows.values())

def main():
    session = requests.Session()
    session.headers.update(monitor.HEADERS)
    try:
        bills = build_official_universe(session)
        bills.sort(key=lambda x:(TARGET_LAWS.index(x["law"]), x["proposal_date"], x["bill_no"]))
        out = []
        alt_count = 0

        for i,b in enumerate(bills,1):
            print(f"[{i}/{len(bills)}] {b['bill_no']} {b['bill_name']}")
            member = member_row(session, b)
            receipt = {} if member else receipt_row(session, b["bill_no"])
            lifecycle = lifecycle_for(session, b, member)

            proposer = representative(
                member.get("PROPOSER")
                or member.get("RST_PROPOSER")
                or member.get("PUBL_PROPOSER")
                or b.get("proposer")
                or receipt.get("PPSR_KIND")
            )

            content = content_enrichment.fetch_bill_content({
                "bill_id": clean(member.get("BILL_ID") or receipt.get("BILL_ID")),
                "bill_no": b["bill_no"],
                "bill_name": b["bill_name"],
                "detail_link": b["detail_url"],
            }, session=session)
            reason = content_enrichment.summarize_reason(content.get("proposal_reason") or "", max_chars=900)
            main_content = summarize_main(content.get("main_content") or "")

            post = {}
            passed = clean(b.get("status_hint")) in ("원안가결","수정가결") or clean(lifecycle.get("plenary_result")) in ("원안가결","수정가결")
            if passed:
                try:
                    post = post_plenary.fetch_post_plenary_status({
                        "bill_id": clean(member.get("BILL_ID") or receipt.get("BILL_ID")),
                        "bill_no": b["bill_no"],
                    }, session=session) or {}
                except Exception as e:
                    print(f"WARN post {b['bill_no']}: {e}")

            successor_no = ""
            successor_name = ""
            if clean(b.get("status_hint")) == "대안반영폐기":
                try:
                    successor = alternative_successor.find_successor_bill(
                        session,
                        {
                            "bill_no": b["bill_no"],
                            "bill_name": b["bill_name"],
                            "matched_law": b["law"],
                            "proposal_date": b["proposal_date"],
                        },
                        lifecycle,
                    ) or {}
                    successor_no = clean(successor.get("bill_no"))
                    successor_name = clean(successor.get("bill_name"))
                    if successor_no:
                        alt_count += 1
                except Exception as e:
                    print(f"WARN successor {b['bill_no']}: {e}")

            current_stage = hub_stage(b, lifecycle, post)
            stage_detail = ""
            if current_stage == "공포":
                bits = [clean(post.get("promulgation_date"))]
                if clean(post.get("promulgation_no")):
                    bits.append("법률 제" + clean(post.get("promulgation_no")) + "호")
                stage_detail = " / ".join([x for x in bits if x])
            elif current_stage == "정부이송":
                stage_detail = clean(post.get("government_transfer_date"))
            elif current_stage == "대안반영폐기" and successor_no:
                stage_detail = f"후속 대안 {successor_no}"

            out.append({
                "법률명": b["law"],
                "의안번호": b["bill_no"],
                "법률안명": b["bill_name"],
                "대표발의자": proposer,
                "발의일": b["proposal_date"],
                "현재단계_HUB": current_stage,
                "단계상세": stage_detail,
                "제안이유": reason,
                "주요내용": main_content,
                "대안반영_후속의안번호": successor_no,
                "대안반영_후속법률안명": successor_name,
                "원문링크": b["detail_url"],
                "국회처리결과": clean(b.get("status_hint")) or clean(lifecycle.get("plenary_result")),
                "BILL_ID": clean(member.get("BILL_ID") or receipt.get("BILL_ID")),
                "내용출처": clean(content.get("content_source")),
                "내용수집오류": clean(content.get("content_error")),
            })

        counts = {law:sum(1 for r in out if r["법률명"]==law) for law in TARGET_LAWS}
        stages = {}
        for r in out:
            stages[r["현재단계_HUB"]] = stages.get(r["현재단계_HUB"],0)+1
        missing_content = [r["의안번호"] for r in out if not r["제안이유"] and not r["주요내용"]]
        missing_proposer = [r["의안번호"] for r in out if not r["대표발의자"]]
        alt_unlinked = [r["의안번호"] for r in out if r["현재단계_HUB"]=="대안반영폐기" and not r["대안반영_후속의안번호"]]

        payload = {
            "start":START.isoformat(), "end":END.isoformat(), "total":len(out),
            "counts":counts, "stage_counts":stages,
            "missing_content":missing_content, "missing_proposer":missing_proposer,
            "alternative_linked_count":alt_count, "alternative_unlinked":alt_unlinked,
            "rows":out,
        }
        OUT_JSON.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        with OUT_CSV.open("w",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=list(out[0].keys()))
            w.writeheader(); w.writerows(out)
        print(json.dumps({k:payload[k] for k in ["total","counts","stage_counts","missing_content","missing_proposer","alternative_linked_count","alternative_unlinked"]},ensure_ascii=False,indent=2))
    finally:
        session.close()

if __name__=="__main__":
    main()
