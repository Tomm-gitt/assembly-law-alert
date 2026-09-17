import json
import re
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import monitor

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
LIST_URL = "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out"
MAX_PAGES = 40


def clean(v):
    return str(v or "").strip()


def extract_detail(session, url, bill_no, law):
    r = session.get(url, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding or "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    text = " ".join(soup.stripped_strings)

    title = ""
    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        t = clean(tag.get_text(" ", strip=True))
        if "법률안" in t and monitor.match_watched_law(t) == law:
            title = t
            break
    if not title:
        m = re.search(rf"({re.escape(law)}[^\n]{{0,140}}?법률안(?:\(대안\))?)", text)
        if m:
            title = clean(m.group(1))
    if not title or monitor.match_watched_law(title) != law:
        return None

    dm = re.search(rf"제\s*{re.escape(bill_no)}\s*호\s*\(\s*(\d{{4}})\s*[.년]\s*(\d{{1,2}})\s*[.월]\s*(\d{{1,2}})", text)
    if not dm:
        return None
    d = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
    if not (START <= d <= END):
        return None

    proposer = ""
    pm = re.search(r"([가-힣A-Za-z·ㆍ\s]{2,40}(?:위원장|의원))\s*,?\s*제\s*" + re.escape(bill_no) + r"\s*호", text)
    if pm:
        proposer = clean(pm.group(1))

    status = ""
    for key in ["대안반영폐기", "철회", "원안가결", "수정가결", "부결", "폐기"]:
        if key in text:
            status = key
            break

    return {
        "law": law,
        "bill_no": bill_no,
        "bill_name": title,
        "proposal_date": d.isoformat(),
        "proposer": proposer,
        "status_hint": status,
        "detail_url": url,
    }


def collect_official(session, law):
    found = {}
    seen_urls = set()
    empty = 0
    for page in range(1, MAX_PAGES + 1):
        params = {
            "sugCd": monitor.AGE,
            "endSugCd": monitor.AGE,
            "scBlNm": "scBlNm_blNm",
            "scBlNmSct": law,
            "pageIndex": str(page),
        }
        r = session.get(LIST_URL, params=params, timeout=30)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or r.encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = clean(a.get("href"))
            m = re.search(r"/gcom/nsmLmSts/out/(\d+)/detailRP", href)
            if not m:
                continue
            url = urljoin(r.url, href)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            links.append((m.group(1), url))
        if not links:
            empty += 1
            if empty >= 2:
                break
            continue
        empty = 0
        for bill_no, url in links:
            try:
                item = extract_detail(session, url, bill_no, law)
            except Exception as e:
                print(f"WARN {law} {bill_no}: {e}")
                continue
            if item:
                found[bill_no] = item
    return list(found.values())


def collect_member(session):
    member = monitor.fetch_recent_member_bills(session, START)
    out = {}
    for b in member:
        law = monitor.match_watched_law(clean(b.get("bill_name")))
        if law not in TARGET_LAWS:
            continue
        d = monitor.parse_date(b.get("proposal_date"))
        if not d or not (START <= d <= END):
            continue
        out[str(b.get("bill_no"))] = {**b, "law": law}
    return out


def main():
    s = requests.Session()
    s.headers.update(monitor.HEADERS)
    try:
        members = collect_member(s)
        official = {}
        for law in TARGET_LAWS:
            rows = collect_official(s, law)
            print(f"OFFICIAL {law}: {len(rows)}")
            for row in rows:
                official[row["bill_no"]] = row

        member_nos = set(members)
        official_nos = set(official)
        only_official = sorted(official_nos - member_nos)
        only_member = sorted(member_nos - official_nos)
        union = sorted(member_nos | official_nos)

        counts = {}
        for law in TARGET_LAWS:
            counts[law] = {
                "member_api": sum(1 for v in members.values() if v["law"] == law),
                "official": sum(1 for v in official.values() if v["law"] == law),
                "union": sum(1 for no in union if (official.get(no) or members.get(no))["law"] == law),
            }

        payload = {
            "start": START.isoformat(),
            "end": END.isoformat(),
            "member_count": len(members),
            "official_count": len(official),
            "union_count": len(union),
            "counts": counts,
            "only_official": [official[n] for n in only_official],
            "only_member": [members[n] for n in only_member],
            "official_rows": [official[n] for n in sorted(official)],
        }
        with open("audit_official_crosscheck.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(json.dumps({k: payload[k] for k in ["member_count","official_count","union_count","counts","only_official","only_member"]}, ensure_ascii=False, indent=2))
    finally:
        s.close()


if __name__ == "__main__":
    main()
