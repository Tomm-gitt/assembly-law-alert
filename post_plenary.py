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
    # Official pages change whitespace/table markup frequently. Search a bounded
    # window after the semantic label and accept dot/slash/dash or Korean date
    # separators. The bounded window prevents accidentally taking a later date.
    match = re.search(
        rf"{re.escape(label)}(?P<gap>.{{0,100}}?)(?P<date>\d{{4}}\s*(?:[.\-/년])\s*\d{{1,2}}\s*(?:[.\-/월])\s*\d{{1,2}}\s*(?:[.일])?)",
        text,
        flags=re.DOTALL,
    )
    return normalize_date(match.group("date")) if match else ""


def _find_number(text: str, label: str) -> str:
    match = re.search(
        rf"{re.escape(label)}.{{0,60}}?제?\s*(\d+)",
        text,
        flags=re.DOTALL,
    )
    return match.group(1) if match else ""


def _find_promulgated_law(text: str) -> str:
    match = re.search(r"공포법률.{0,40}?(?:법률\s*)?([^\n|]{2,120})", text, flags=re.DOTALL)
    if not match:
        return ""
    value = clean(match.group(1))
    value = re.split(r"(?:공포안|바로보기|정부이송|기본정보)", value, maxsplit=1)[0]
    return clean(value)


def _parse_status_html(html_text: str, source: str, url: str) -> Dict[str, str]:
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Keep both line-oriented and flattened text. Some official pages put labels
    # and values in separate table cells; others render them on one line.
    lines = [line.strip() for line in soup.get_text("\n", strip=True).splitlines() if line.strip()]
    line_text = "\n".join(lines)
    flat_text = " ".join(lines)

    government_transfer_date = _find_date(line_text, "정부이송일") or _find_date(flat_text, "정부이송일")
    promulgation_date = _find_date(line_text, "공포일자") or _find_date(flat_text, "공포일자")
    promulgation_no = _find_number(line_text, "공포번호") or _find_number(flat_text, "공포번호")
    promulgated_law = _find_promulgated_law(line_text) or _find_promulgated_law(flat_text)

    return {
        "government_transfer_date": government_transfer_date,
        "promulgation_date": promulgation_date,
        "promulgation_no": promulgation_no,
        "promulgated_law": promulgated_law,
        "post_plenary_source": source,
        "post_plenary_url": url,
    }


def _merge_result(base: Dict[str, str], incoming: Dict[str, str]) -> Dict[str, str]:
    merged = dict(base)
    for key in (
        "government_transfer_date",
        "promulgation_date",
        "promulgation_no",
        "promulgated_law",
    ):
        if not clean(merged.get(key)) and clean(incoming.get(key)):
            merged[key] = incoming[key]
    if not clean(merged.get("post_plenary_source")) and clean(incoming.get("post_plenary_source")):
        merged["post_plenary_source"] = incoming["post_plenary_source"]
        merged["post_plenary_url"] = incoming.get("post_plenary_url", "")
    return merged


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
        # 국민참여입법센터 상세는 정부이송/공포정보를 명시적으로 제공하므로
        # 후속단계의 1순위 원천으로 사용하고, LIKMS는 보완 원천으로 사용한다.
        urls = [
            ("국민참여입법센터", build_lawmaking_url(bill)),
            ("국회 의안정보시스템", build_likms_url(bill)),
        ]
        combined: Dict[str, str] = {}
        for source, url in urls:
            if not url:
                continue
            try:
                response = session.get(url, timeout=30)
                response.raise_for_status()
                response.encoding = response.apparent_encoding or response.encoding or "utf-8"
                result = _parse_status_html(response.text, source, url)
                combined = _merge_result(combined, result)
                if combined.get("government_transfer_date") and combined.get("promulgation_date") and combined.get("promulgation_no"):
                    break
            except Exception as exc:
                print(f"[WARN] {source} 후속단계 조회 실패: {bill.get('bill_no') or bill.get('bill_id')} / {exc}")
        return combined
    finally:
        if own_session:
            session.close()
