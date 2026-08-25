import re
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

LIKMS_BASE = "https://likms.assembly.go.kr/bill/billDetail.do"
LAWMAKING_BASE = "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out"


def clean(text) -> str:
    return str(text or "").replace("\xa0", " ").strip()


def normalize_date(value: str) -> str:
    digits = re.sub(r"\D", "", clean(value))
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def build_likms_url(bill: Dict) -> str:
    bill_id = clean(bill.get("bill_id"))
    if not bill_id:
        return ""
    return f"{LIKMS_BASE}?billId={bill_id}&ageFrom=22&ageTo=22"


def build_lawmaking_url(bill: Dict) -> str:
    digits = re.sub(r"\D", "", clean(bill.get("bill_no")))
    return f"{LAWMAKING_BASE}/{digits}/detailRP" if digits else ""


def _find_date(text: str, label: str) -> str:
    match = re.search(
        rf"{re.escape(label)}\s*[:：]?\s*(\d{{4}}[.\-/]\s*\d{{1,2}}[.\-/]\s*\d{{1,2}}\.?)",
        text,
    )
    return normalize_date(match.group(1)) if match else ""


def _find_number(text: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}\s*[:：]?\s*제?\s*(\d+)", text)
    return match.group(1) if match else ""


def _parse_status_html(html_text: str, source: str, url: str) -> Dict[str, str]:
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = "\n".join(line.strip() for line in soup.get_text("\n", strip=True).splitlines() if line.strip())

    government_transfer_date = _find_date(text, "정부이송일")
    promulgation_date = _find_date(text, "공포일자")
    promulgation_no = _find_number(text, "공포번호")

    promulgated_law = ""
    law_match = re.search(r"공포법률\s*(?:법률\s*)?([^\n]+)", text)
    if law_match:
        promulgated_law = clean(law_match.group(1))

    return {
        "government_transfer_date": government_transfer_date,
        "promulgation_date": promulgation_date,
        "promulgation_no": promulgation_no,
        "promulgated_law": promulgated_law,
        "post_plenary_source": source,
        "post_plenary_url": url,
    }


def fetch_post_plenary_status(
    bill: Dict,
    session: Optional[requests.Session] = None,
) -> Dict[str, str]:
    own_session = session is None
    session = session or requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (assembly-law-alert/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9",
        }
    )

    try:
        urls = [
            ("국회 의안정보시스템", build_likms_url(bill)),
            ("국민참여입법센터", build_lawmaking_url(bill)),
        ]
        fallback = {}
        for source, url in urls:
            if not url:
                continue
            try:
                response = session.get(url, timeout=30)
                response.raise_for_status()
                response.encoding = response.apparent_encoding or response.encoding or "utf-8"
                result = _parse_status_html(response.text, source, url)
                if result.get("government_transfer_date") or result.get("promulgation_date"):
                    return result
                if not fallback:
                    fallback = result
            except Exception as exc:
                print(f"[WARN] {source} 후속단계 조회 실패: {bill.get('bill_no') or bill.get('bill_id')} / {exc}")
        return fallback
    finally:
        if own_session:
            session.close()
