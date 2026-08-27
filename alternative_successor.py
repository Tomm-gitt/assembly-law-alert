import re
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import monitor


SEARCH_WINDOW_DAYS_BEFORE = 7
SEARCH_WINDOW_DAYS_AFTER = 120
RECEIPT_PAGE_SIZE = 100
MAX_RECEIPT_PAGES = 100
MAX_OFFICIAL_LIST_PAGES = 30
OFFICIAL_LIST_URL = "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out"


def clean(value) -> str:
    return str(value or "").strip()


def is_alternative_reflection_result(value: str) -> bool:
    text = re.sub(r"\s+", "", clean(value))
    return "대안반영폐기" in text


def _is_committee_alternative_bill(row: Dict, watched_law: str) -> bool:
    if clean(row.get("ERACO")) != monitor.ERACO:
        return False
    if "법률안" not in clean(row.get("BILL_KIND")):
        return False

    bill_name = clean(row.get("BILL_NM"))
    if monitor.match_watched_law(bill_name) != watched_law:
        return False

    normalized_name = monitor.normalize_law_name(bill_name)
    normalized_law = monitor.normalize_law_name(watched_law)
    if not normalized_name.startswith(normalized_law):
        return False

    proposer_kind = clean(row.get("PPSR_KIND"))
    if "(대안)" not in bill_name and "대안" not in bill_name:
        if "위원" not in proposer_kind:
            return False
    return True


def _date_rank(value: str, anchor: date) -> Tuple[int, int]:
    parsed = monitor.parse_date(value)
    if not parsed:
        return (2, 9999)
    delta = (parsed - anchor).days
    if delta >= 0:
        return (0, delta)
    return (1, abs(delta))


def _candidate_from_row(row: Dict) -> Dict:
    return {
        "bill_id": clean(row.get("BILL_ID")),
        "bill_no": clean(row.get("BILL_NO")),
        "bill_name": clean(row.get("BILL_NM")),
        "proposal_date": clean(row.get("PPSL_DT")),
        "proposer_kind": clean(row.get("PPSR_KIND")) or "위원회",
        "process_result": clean(row.get("PROC_RSLT")),
        "detail_link": clean(row.get("LINK_URL")),
        "source": monitor.RECEIPT_API,
    }


def _collect_receipt_candidates(
    session: requests.Session,
    watched_law: str,
    start: date,
    end: date,
    extra_params: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    candidates: Dict[str, Dict] = {}
    older_pages_in_a_row = 0

    for page in range(1, MAX_RECEIPT_PAGES + 1):
        params = {
            "pIndex": str(page),
            "pSize": str(RECEIPT_PAGE_SIZE),
            **(extra_params or {}),
        }
        data = monitor.request_api(session, monitor.RECEIPT_API, params)
        rows = monitor.parse_rows(data, monitor.RECEIPT_API)
        if not rows:
            break

        page_dates = []
        for row in rows:
            proposal_date = monitor.parse_date(row.get("PPSL_DT"))
            if proposal_date:
                page_dates.append(proposal_date)
            if not proposal_date or not (start <= proposal_date <= end):
                continue
            if not _is_committee_alternative_bill(row, watched_law):
                continue

            candidate = _candidate_from_row(row)
            key = candidate.get("bill_id") or candidate.get("bill_no")
            if key:
                candidates[key] = candidate

        if page_dates and max(page_dates) < start:
            older_pages_in_a_row += 1
        else:
            older_pages_in_a_row = 0
        if older_pages_in_a_row >= 3:
            break

    return list(candidates.values())


def _extract_official_detail_candidate(
    session: requests.Session,
    detail_url: str,
    bill_no: str,
    watched_law: str,
    start: date,
    end: date,
) -> Optional[Dict]:
    response = session.get(detail_url, timeout=30)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    text = " ".join(soup.stripped_strings)

    title = ""
    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        value = clean(tag.get_text(" ", strip=True))
        if "법률안" in value:
            title = value
            break
    if not title:
        match = re.search(rf"({re.escape(watched_law)}[^\n]{{0,120}}?법률안(?:\(대안\))?)", text)
        if match:
            title = clean(match.group(1))

    if not title or monitor.match_watched_law(title) != watched_law:
        return None
    if "대안" not in title:
        return None

    info_match = re.search(
        rf"([^|\n]{{0,50}}위원장)\s*,?\s*제\s*{re.escape(bill_no)}\s*호\s*\(\s*(\d{{4}})\s*[.년]\s*(\d{{1,2}})\s*[.월]\s*(\d{{1,2}})",
        text,
    )
    if info_match:
        proposer = clean(info_match.group(1))
        proposal_date = date(int(info_match.group(2)), int(info_match.group(3)), int(info_match.group(4)))
    else:
        date_match = re.search(
            rf"제\s*{re.escape(bill_no)}\s*호\s*\(\s*(\d{{4}})\s*[.년]\s*(\d{{1,2}})\s*[.월]\s*(\d{{1,2}})",
            text,
        )
        if not date_match:
            return None
        proposal_date = date(int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3)))
        proposer_match = re.search(r"([가-힣A-Za-z·ㆍ\s]{2,40}위원장)", text)
        proposer = clean(proposer_match.group(1)) if proposer_match else "위원회"

    if not (start <= proposal_date <= end):
        return None
    if "위원장" not in proposer and "위원" not in proposer:
        return None

    return {
        "bill_id": "",
        "bill_no": bill_no,
        "bill_name": title,
        "proposal_date": proposal_date.isoformat(),
        "proposer_kind": proposer,
        "process_result": "",
        "detail_link": detail_url,
        "source": "opinion.lawmaking.go.kr",
    }


def _collect_official_lawmaking_candidates(
    session: requests.Session,
    watched_law: str,
    start: date,
    end: date,
) -> List[Dict]:
    """Search the official National Assembly-linked lawmaking list, then verify each candidate detail page."""
    candidates: Dict[str, Dict] = {}
    seen_detail_urls = set()
    empty_pages = 0

    for page in range(1, MAX_OFFICIAL_LIST_PAGES + 1):
        params = {
            "sugCd": monitor.AGE,
            "endSugCd": monitor.AGE,
            "scBlNm": "scBlNm_blNm",
            "scBlNmSct": watched_law,
            "pageIndex": str(page),
        }
        response = session.get(OFFICIAL_LIST_URL, params=params, timeout=30)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding or "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")

        page_links = []
        for anchor in soup.find_all("a", href=True):
            href = clean(anchor.get("href"))
            match = re.search(r"/gcom/nsmLmSts/out/(\d+)/detailRP", href)
            if not match:
                continue
            bill_no = match.group(1)
            detail_url = urljoin(response.url, href)
            if detail_url in seen_detail_urls:
                continue
            seen_detail_urls.add(detail_url)
            page_links.append((bill_no, detail_url))

        if not page_links:
            empty_pages += 1
            if empty_pages >= 2:
                break
            continue
        empty_pages = 0

        for bill_no, detail_url in page_links:
            try:
                candidate = _extract_official_detail_candidate(
                    session,
                    detail_url,
                    bill_no,
                    watched_law,
                    start,
                    end,
                )
            except Exception as exc:
                print(f"[WARN] 공식 입법현황 후보 상세조회 실패: {bill_no} / {exc}")
                continue
            if candidate:
                candidates[bill_no] = candidate

    return list(candidates.values())


def fetch_candidate_alternatives(session: requests.Session, watched_law: str, anchor_date: date) -> List[Dict]:
    start = anchor_date - timedelta(days=SEARCH_WINDOW_DAYS_BEFORE)
    end = anchor_date + timedelta(days=SEARCH_WINDOW_DAYS_AFTER)

    # 1순위: 국민참여입법센터의 공식 국회입법현황 목록/상세에서 위원회 대안을 찾는다.
    official = _collect_official_lawmaking_candidates(session, watched_law, start, end)
    if official:
        print(
            f"[INFO] 공식 국회입법현황에서 대안 후보 발견: {watched_law} / "
            f"{[c.get('bill_no') for c in official]}"
        )
        return official

    # 2순위: 공식 목록 탐색 실패 시 BILLRCP를 보조 후보원으로 사용한다.
    print(f"[WARN] 공식 국회입법현황 후보 없음. BILLRCP 보조탐색: {watched_law}")
    candidates = _collect_receipt_candidates(
        session,
        watched_law,
        start,
        end,
        {"BILL_NM": watched_law},
    )
    if candidates:
        return candidates

    print(f"[INFO] BILLRCP 법률명 필터 후보 없음. 전체 접수목록으로 재탐색: {watched_law}")
    return _collect_receipt_candidates(session, watched_law, start, end)


def find_successor_bill(session: requests.Session, original_entry: Dict, current_lifecycle: Dict) -> Optional[Dict]:
    watched_law = clean(original_entry.get("matched_law"))
    if not watched_law:
        return None

    anchor = (
        monitor.parse_date(current_lifecycle.get("committee_process_date"))
        or monitor.parse_date(current_lifecycle.get("plenary_date"))
        or monitor.parse_date(original_entry.get("proposal_date"))
    )
    if not anchor:
        return None

    candidates = fetch_candidate_alternatives(session, watched_law, anchor)
    original_no = clean(original_entry.get("bill_no"))
    candidates = [c for c in candidates if c.get("bill_no") and c.get("bill_no") != original_no]
    if not candidates:
        return None

    ranked = sorted(
        candidates,
        key=lambda c: (
            0 if "(대안)" in clean(c.get("bill_name")) else 1,
            *_date_rank(clean(c.get("proposal_date")), anchor),
            clean(c.get("bill_no")),
        ),
    )

    best = ranked[0]
    if len(ranked) > 1:
        first_key = (
            0 if "(대안)" in clean(ranked[0].get("bill_name")) else 1,
            *_date_rank(clean(ranked[0].get("proposal_date")), anchor),
        )
        second_key = (
            0 if "(대안)" in clean(ranked[1].get("bill_name")) else 1,
            *_date_rank(clean(ranked[1].get("proposal_date")), anchor),
        )
        if first_key == second_key:
            print(f"[WARN] 대안 후보 복수로 자동승계 보류: {original_no} / {ranked[0].get('bill_no')}, {ranked[1].get('bill_no')}")
            return None

    return best


def register_successor(seen: Dict[str, Dict], original_bill_id: str, original_entry: Dict, successor: Dict, now: str) -> Dict:
    successor_id = clean(successor.get("bill_id"))
    successor_no = clean(successor.get("bill_no"))
    if not successor_id or not successor_no:
        raise ValueError("위원회 대안의 BILL_ID/BILL_NO가 없습니다.")

    original_no = clean(original_entry.get("bill_no"))
    original_entry["alternative_reflection"] = {
        "result": "대안반영폐기",
        "successor_bill_id": successor_id,
        "successor_bill_no": successor_no,
        "successor_bill_name": clean(successor.get("bill_name")),
        "linked_at": now,
    }
    original_entry["tracking_continued_as"] = successor_no

    existing = seen.get(successor_id)
    if existing:
        origins = existing.get("origin_bill_nos") if isinstance(existing.get("origin_bill_nos"), list) else []
        if original_no and original_no not in origins:
            origins.append(original_no)
        existing["origin_bill_nos"] = origins
        if existing.get("status_tracking") is not False:
            existing["status_tracking"] = True
        return existing

    successor_entry = {
        "bill_name": clean(successor.get("bill_name")),
        "bill_no": successor_no,
        "first_seen_at": now,
        "matched_law": clean(original_entry.get("matched_law")),
        "proposal_date": clean(successor.get("proposal_date")),
        "status_tracking": True,
        "origin_bill_nos": [original_no] if original_no else [],
        "tracking_inherited_from": original_no,
        "inherited_reason": "대안반영폐기 자동승계",
        "detail_link": clean(successor.get("detail_link")),
        "successor_tracking_started_at": now,
        "lifecycle": {},
    }
    seen[successor_id] = successor_entry
    return successor_entry
