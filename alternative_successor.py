import re
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import requests

import monitor


SEARCH_WINDOW_DAYS_BEFORE = 7
SEARCH_WINDOW_DAYS_AFTER = 120
MAX_RECEIPT_PAGES = 10


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
    # 동일 법률의 일반 의원안과 혼동하지 않도록 '대안' 제목 또는 위원회 제안만 허용한다.
    if "(대안)" not in bill_name and "대안" not in bill_name:
        if "위원" not in proposer_kind:
            return False
    return True


def _date_rank(value: str, anchor: date) -> Tuple[int, int]:
    parsed = monitor.parse_date(value)
    if not parsed:
        return (2, 9999)
    delta = (parsed - anchor).days
    # 대안반영폐기 이후에 제안된 대안을 최우선. 며칠 먼저 접수된 경우만 차선으로 허용한다.
    if delta >= 0:
        return (0, delta)
    return (1, abs(delta))


def fetch_candidate_alternatives(session: requests.Session, watched_law: str, anchor_date: date) -> List[Dict]:
    start = anchor_date - timedelta(days=SEARCH_WINDOW_DAYS_BEFORE)
    end = anchor_date + timedelta(days=SEARCH_WINDOW_DAYS_AFTER)
    candidates: List[Dict] = []

    for page in range(1, MAX_RECEIPT_PAGES + 1):
        data = monitor.request_api(session, monitor.RECEIPT_API, {"pIndex": str(page), "pSize": str(monitor.PAGE_SIZE)})
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
            candidates.append({
                "bill_id": clean(row.get("BILL_ID")),
                "bill_no": clean(row.get("BILL_NO")),
                "bill_name": clean(row.get("BILL_NM")),
                "proposal_date": clean(row.get("PPSL_DT")),
                "proposer_kind": clean(row.get("PPSR_KIND")) or "위원회",
                "process_result": clean(row.get("PROC_RSLT")),
                "detail_link": clean(row.get("LINK_URL")),
                "source": monitor.RECEIPT_API,
            })

        if page_dates and max(page_dates) < start:
            break
        if len(rows) < monitor.PAGE_SIZE:
            break

    return candidates


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
        # 동일 우선순위 후보가 둘 이상이면 오탐 방지를 위해 자동 연결하지 않는다.
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
        # 직원이 이미 대안 자체를 제외한 경우 false를 존중한다.
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
