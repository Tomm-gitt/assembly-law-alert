import re
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import monitor

LIKMS_DETAIL_URL = "https://likms.assembly.go.kr/bill/bi/billDetailPage.do"
BILL_NO_RE = re.compile(r"(?<!\d)(2\d{6})(?!\d)")
URL_RE = re.compile(r"(?:https?://[^\"'<>\s]+|/[A-Za-z0-9_./?=&%-]+\.do(?:\?[^\"'<>\s]*)?)")


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _request(session: requests.Session, url: str, *, params=None, referer: str = "") -> requests.Response:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if referer:
        headers["Referer"] = referer
    response = session.get(url, params=params, headers=headers, timeout=30, allow_redirects=True)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    return response


def _bill_numbers(text: str, allowed: Set[str]) -> Set[str]:
    if not text:
        return set()
    return {m.group(1) for m in BILL_NO_RE.finditer(text) if m.group(1) in allowed}


def _alternative_context_numbers(html_text: str, allowed: Set[str]) -> Set[str]:
    """Return candidate bill numbers that appear in explicit LIKMS alternative-info context.

    Fail closed: a candidate number must occur near the literal '대안정보'/'대안' context,
    not merely somewhere on the detail page.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    found: Set[str] = set()

    # 1) DOM blocks containing the alternative-info label.
    for node in soup.find_all(string=re.compile(r"대안정보|대안")):
        parent = node.parent
        for _ in range(5):
            if not parent:
                break
            text = clean(parent.get_text(" ", strip=True))
            nums = _bill_numbers(text, allowed)
            if nums:
                found.update(nums)
            parent = parent.parent

    # 2) Raw source windows around alternative-related tokens; this captures hidden
    #    tab payloads or script variables that are not visible DOM text.
    compact = str(html_text or "")
    for m in re.finditer(r"대안정보|대안", compact):
        start = max(0, m.start() - 2500)
        end = min(len(compact), m.end() + 5000)
        found.update(_bill_numbers(compact[start:end], allowed))

    return found


def _discover_alt_related_urls(base_url: str, html_text: str) -> List[str]:
    """Discover same-site URLs/actions associated with the LIKMS alternative tab.

    The LIKMS frontend has changed routes over time. Rather than hard-code one AJAX
    endpoint, inspect links, data attributes, onclick handlers and nearby scripts.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    urls: List[str] = []
    seen = set()

    def add(raw: str):
        raw = clean(raw)
        if not raw:
            return
        # Pull URL-like fragments out of javascript attributes.
        candidates = URL_RE.findall(raw) or [raw]
        for candidate in candidates:
            candidate = candidate.replace("&amp;", "&").strip("'\" ")
            if not candidate:
                continue
            absolute = urljoin(base_url, candidate)
            parsed = urlparse(absolute)
            if parsed.netloc != "likms.assembly.go.kr":
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            urls.append(absolute)

    for tag in soup.find_all(True):
        text = clean(tag.get_text(" ", strip=True))
        attrs_blob = " ".join(clean(v) for v in tag.attrs.values() if isinstance(v, str))
        blob = f"{text} {attrs_blob}"
        if "대안" not in blob and "alternative" not in blob.lower() and "replace" not in blob.lower():
            continue
        for attr in ("href", "onclick", "data-url", "data-href", "action"):
            value = tag.get(attr)
            if value:
                add(str(value))

    for script in soup.find_all("script"):
        text = script.string or script.get_text(" ", strip=False)
        if not text:
            continue
        if "대안" not in text and "alternative" not in text.lower() and "replace" not in text.lower():
            continue
        for match in URL_RE.findall(text):
            add(match)

    return urls[:20]


def fetch_likms_successor_bill_nos(
    session: requests.Session,
    original_bill_id: str,
    candidate_bill_nos: Iterable[str],
) -> Tuple[List[str], List[str]]:
    """Resolve successor bill numbers from LIKMS' official alternative-info surface.

    Returns (matched_bill_nos, evidence_urls). Only numbers already present in the
    independently collected candidate set are eligible, preventing unrelated bill
    numbers on the page from becoming successors.
    """
    original_bill_id = clean(original_bill_id)
    allowed = {clean(x) for x in candidate_bill_nos if clean(x)}
    if not original_bill_id or not allowed:
        return [], []

    detail_response = _request(
        session,
        LIKMS_DETAIL_URL,
        params={"billId": original_bill_id, "currMenuNo": "2600044"},
    )
    detail_url = detail_response.url
    evidence_urls = [detail_url]
    matched = _alternative_context_numbers(detail_response.text, allowed)

    # If the relation is loaded by a tab/AJAX action, follow only alternative-related
    # same-host URLs discovered from the official page source.
    for url in _discover_alt_related_urls(detail_url, detail_response.text):
        try:
            response = _request(session, url, referer=detail_url)
        except Exception as exc:
            print(f"[WARN] LIKMS 대안정보 보조경로 조회 실패: {url} / {exc}")
            continue
        evidence_urls.append(response.url)
        matched.update(_alternative_context_numbers(response.text, allowed))
        # Dedicated alternative endpoints may omit the '대안정보' heading. If the URL
        # itself is alternative-related, candidate numbers in the body are accepted.
        lower_url = response.url.lower()
        if "alt" in lower_url or "replace" in lower_url or "%EB%8C%80%EC%95%88" in lower_url:
            matched.update(_bill_numbers(BeautifulSoup(response.text, "html.parser").get_text(" "), allowed))

    return sorted(matched), list(dict.fromkeys(evidence_urls))


def validate_successor_candidate(candidate: Dict, watched_law: str) -> bool:
    bill_name = clean(candidate.get("bill_name") or candidate.get("BILL_NAME") or candidate.get("BILL_NM"))
    if monitor.match_watched_law(bill_name) != watched_law:
        return False
    proposer = clean(candidate.get("proposer_kind") or candidate.get("PPSR_KIND") or candidate.get("PROPOSER"))
    return "대안" in bill_name or "위원" in proposer
