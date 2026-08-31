import re
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

LIKMS_BASE = "https://likms.assembly.go.kr/bill/billDetail.do"
LAWMAKING_BASE = "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
}


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
    """Find the first calendar date immediately after a semantic label.

    Official pages commonly render dates as `2026. 2. 27.` with whitespace
    between the dotted components.  Instead of trying to enumerate every date
    separator combination, inspect only a short window after the label and
    extract the first year/month/day triple separated by non-digits.
    """
    start = text.find(label)
    if start < 0:
        return ""

    window = text[start + len(label): start + len(label) + 120]
    match = re.search(r"(\d{4})\D{1,12}(\d{1,2})\D{1,12}(\d{1,2})", window)
    if not match:
        return ""

    year, month, day = (int(value) for value in match.groups())
    if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def _find_number(text: str, label: str) -> str:
    match = re.search(
        rf"{re.escape(label)}.{{0,80}}?제?\s*(\d+)",
        text,
        flags=re.DOTALL,
    )
    return match.group(1) if match else ""


def _find_promulgated_law(text: str) -> str:
    match = re.search(r"공포법률.{0,60}?(?:법률\s*)?([^\n|]{2,120})", text, flags=re.DOTALL)
    if not match:
        return ""
    value = clean(match.group(1))
    value = re.split(r"(?:공포안|바로보기|정부이송|기본정보)", value, maxsplit=1)[0]
    return clean(value)


def _parse_status_html(html_text: str, source: str, url: str) -> Dict[str, str]:
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

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


def _fetch_lawmaking_html(url: str) -> str:
    with requests.Session() as s:
        s.headers.update(BROWSER_HEADERS)
        try:
            s.get(LAWMAKING_BASE, timeout=20)
        except Exception:
            pass
        response = s.get(
            url,
            headers={"Referer": LAWMAKING_BASE + "/"},
            timeout=30,
            allow_redirects=True,
        )
        response.raise_for_status()
        text = response.content.decode("utf-8", errors="replace")
        print(
            f"[DEBUG] 국민참여입법센터 응답: status={response.status_code} "
            f"bytes={len(response.content)} final={response.url} "
            f"gov_label={'정부이송일' in text} prom_label={'공포일자' in text}"
        )
        return text


def _fetch_generic_html(session: requests.Session, url: str, source: str) -> str:
    response = session.get(url, headers=BROWSER_HEADERS, timeout=30, allow_redirects=True)
    response.raise_for_status()
    encoding = response.encoding or "utf-8"
    try:
        text = response.content.decode(encoding, errors="replace")
    except LookupError:
        text = response.content.decode("utf-8", errors="replace")
    print(
        f"[DEBUG] {source} 응답: status={response.status_code} bytes={len(response.content)} "
        f"final={response.url} gov_label={'정부이송일' in text} prom_label={'공포일자' in text}"
    )
    return text


def fetch_post_plenary_status(
    bill: Dict,
    session: Optional[requests.Session] = None,
) -> Dict[str, str]:
    own_session = session is None
    session = session or requests.Session()

    try:
        urls = [
            ("국민참여입법센터", build_lawmaking_url(bill)),
            ("국회 의안정보시스템", build_likms_url(bill)),
        ]
        combined: Dict[str, str] = {}
        for source, url in urls:
            if not url:
                continue
            try:
                if source == "국민참여입법센터":
                    html_text = _fetch_lawmaking_html(url)
                else:
                    html_text = _fetch_generic_html(session, url, source)
                result = _parse_status_html(html_text, source, url)
                print(
                    f"[DEBUG] {source} 파싱: government_transfer_date={result.get('government_transfer_date') or '-'} "
                    f"promulgation_date={result.get('promulgation_date') or '-'} "
                    f"promulgation_no={result.get('promulgation_no') or '-'}"
                )
                combined = _merge_result(combined, result)
                if (
                    combined.get("government_transfer_date")
                    and combined.get("promulgation_date")
                    and combined.get("promulgation_no")
                ):
                    break
            except Exception as exc:
                print(
                    f"[WARN] {source} 후속단계 조회 실패: "
                    f"{bill.get('bill_no') or bill.get('bill_id')} / {exc}"
                )
        return combined
    finally:
        if own_session:
            session.close()
