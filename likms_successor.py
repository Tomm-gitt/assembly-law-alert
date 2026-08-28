import re
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import monitor

LIKMS_DETAIL_URL = "https://likms.assembly.go.kr/bill/bi/billDetailPage.do"
LIKMS_SUGGEST_URL = "https://likms.assembly.go.kr/bill/bi/bill/state/suggestBillPage.do"
BILL_NO_RE = re.compile(r"(?<!\d)(2\d{6})(?!\d)")
URL_RE = re.compile(r"(?:https?://[^\"'<>\s]+|/[A-Za-z0-9_./?=&%-]+\.do(?:\?[^\"'<>\s]*)?)")


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _headers(referer: str = "") -> Dict[str, str]:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "X-Requested-With": "XMLHttpRequest",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _get(session: requests.Session, url: str, *, params=None, referer: str = "") -> requests.Response:
    response = session.get(url, params=params, headers=_headers(referer), timeout=30, allow_redirects=True)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    return response


def _post(session: requests.Session, url: str, *, data=None, referer: str = "") -> requests.Response:
    response = session.post(url, data=data, headers=_headers(referer), timeout=30, allow_redirects=True)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    return response


def _bill_numbers(text: str, allowed: Optional[Set[str]] = None) -> Set[str]:
    if not text:
        return set()
    values = {m.group(1) for m in BILL_NO_RE.finditer(text)}
    if allowed:
        values &= allowed
    return values


def _alternative_context_numbers(html_text: str, allowed: Optional[Set[str]] = None) -> Set[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    found: Set[str] = set()

    for node in soup.find_all(string=re.compile(r"대안정보|대안")):
        parent = node.parent
        for _ in range(5):
            if not parent:
                break
            found.update(_bill_numbers(clean(parent.get_text(" ", strip=True)), allowed))
            parent = parent.parent

    raw = str(html_text or "")
    for m in re.finditer(r"대안정보|대안", raw):
        start = max(0, m.start() - 2500)
        end = min(len(raw), m.end() + 5000)
        found.update(_bill_numbers(raw[start:end], allowed))
    return found


def _discover_alt_related_urls(base_url: str, html_text: str) -> List[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    urls: List[str] = []
    seen = set()

    def add(raw: str):
        raw = clean(raw)
        if not raw:
            return
        for candidate in URL_RE.findall(raw):
            candidate = candidate.replace("&amp;", "&").strip("'\" ")
            absolute = urljoin(base_url, candidate)
            parsed = urlparse(absolute)
            if parsed.netloc != "likms.assembly.go.kr" or ".do" not in parsed.path:
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            urls.append(absolute)

    for tag in soup.find_all(True):
        text = clean(tag.get_text(" ", strip=True))
        attrs_blob = " ".join(clean(v) for v in tag.attrs.values() if isinstance(v, str))
        blob = f"{text} {attrs_blob}"
        if "대안" not in blob and "suggest" not in blob.lower() and "alternative" not in blob.lower():
            continue
        for attr in ("href", "onclick", "data-url", "data-href", "action"):
            value = tag.get(attr)
            if value:
                add(str(value))

    for script in soup.find_all("script"):
        text = script.string or script.get_text(" ", strip=False)
        if not text:
            continue
        if "대안" not in text and "suggest" not in text.lower() and "alternative" not in text.lower():
            continue
        for match in URL_RE.findall(text):
            add(match)

    return urls[:20]


def _consume_response(
    response: requests.Response,
    matched: Set[str],
    evidence_urls: List[str],
    *,
    dedicated: bool = False,
) -> None:
    evidence_urls.append(response.url)
    matched.update(_alternative_context_numbers(response.text))
    if dedicated:
        body_text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
        matched.update(_bill_numbers(body_text))


def fetch_likms_successor_bill_nos(
    session: requests.Session,
    original_bill_id: str,
    candidate_bill_nos: Iterable[str] = (),
) -> Tuple[List[str], List[str]]:
    """Read the official LIKMS alternative-information surface first.

    The optional candidate list is only a downstream filter/corroboration aid. Relationship
    discovery itself does not depend on the 국민참여입법센터 candidate list.
    """
    original_bill_id = clean(original_bill_id)
    if not original_bill_id:
        return [], []

    detail_response = _get(
        session,
        LIKMS_DETAIL_URL,
        params={"billId": original_bill_id, "currMenuNo": "2600044"},
    )
    detail_url = detail_response.url
    evidence_urls: List[str] = []
    matched: Set[str] = set()
    _consume_response(detail_response, matched, evidence_urls)

    direct_attempts = [
        ("GET", {"billId": original_bill_id}),
        ("GET", {"billId": original_bill_id, "currMenuNo": "2600044"}),
        ("POST", {"billId": original_bill_id}),
        ("POST", {"billId": original_bill_id, "currMenuNo": "2600044"}),
    ]
    for method, payload in direct_attempts:
        try:
            if method == "GET":
                response = _get(session, LIKMS_SUGGEST_URL, params=payload, referer=detail_url)
            else:
                response = _post(session, LIKMS_SUGGEST_URL, data=payload, referer=detail_url)
        except Exception as exc:
            print(f"[WARN] LIKMS 대안정보 직접조회 실패: {method} / {payload} / {exc}")
            continue
        before = set(matched)
        _consume_response(response, matched, evidence_urls, dedicated=True)
        print(
            f"[INFO] LIKMS 대안정보 직접조회: {method} / {payload} / "
            f"status={response.status_code} / len={len(response.text)} / "
            f"new_matches={sorted(matched - before)}"
        )

    for url in _discover_alt_related_urls(detail_url, detail_response.text):
        if url.startswith(LIKMS_SUGGEST_URL):
            continue
        try:
            response = _get(session, url, referer=detail_url)
        except Exception as exc:
            print(f"[WARN] LIKMS 대안정보 보조경로 조회 실패: {url} / {exc}")
            continue
        _consume_response(response, matched, evidence_urls)

    candidate_set = {clean(x) for x in candidate_bill_nos if clean(x)}
    if candidate_set:
        matched &= candidate_set
    return sorted(matched), list(dict.fromkeys(evidence_urls))


def validate_successor_candidate(candidate: Dict, watched_law: str) -> bool:
    bill_name = clean(candidate.get("bill_name") or candidate.get("BILL_NAME") or candidate.get("BILL_NM"))
    if monitor.match_watched_law(bill_name) != watched_law:
        return False
    proposer = clean(candidate.get("proposer_kind") or candidate.get("PPSR_KIND") or candidate.get("PROPOSER"))
    return "대안" in bill_name or "위원" in proposer
