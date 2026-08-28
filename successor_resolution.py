from typing import Dict, Optional

import requests

import alternative_successor
import likms_successor
import monitor
import status_monitor


def clean(value) -> str:
    return status_monitor.clean(value)


def _exact_api_row(session: requests.Session, bill_no: str) -> Optional[Dict]:
    lookup = {"bill_no": bill_no}
    endpoints = [
        (monitor.MEMBER_BILLS_API, True),
        (status_monitor.PROCESSED_API, True),
    ]
    for endpoint, include_age in endpoints:
        try:
            row = status_monitor.fetch_matching_row(
                session,
                endpoint,
                lookup,
                include_age=include_age,
            )
        except Exception as exc:
            print(f"[WARN] 후속대안 국회 API 검증 실패: {endpoint} / {bill_no} / {exc}")
            continue
        if row and clean(row.get("BILL_NO")) == bill_no:
            return row

    # BILLRCP is only a final fallback because it is unreliable for committee alternatives.
    try:
        data = monitor.request_api(
            session,
            monitor.RECEIPT_API,
            {"pIndex": "1", "pSize": "100", "BILL_NO": bill_no},
        )
        rows = monitor.parse_rows(data, monitor.RECEIPT_API)
        for row in rows:
            if clean(row.get("BILL_NO")) == bill_no:
                return row
    except Exception as exc:
        print(f"[WARN] 후속대안 BILLRCP 검증 실패: {bill_no} / {exc}")
    return None


def _merge_candidate_with_api(candidate: Dict, row: Dict) -> Dict:
    bill_name = clean(row.get("BILL_NAME") or row.get("BILL_NM") or candidate.get("bill_name"))
    proposer = clean(
        row.get("PPSR_KIND")
        or row.get("PROPOSER")
        or row.get("RST_PROPOSER")
        or row.get("PUBL_PROPOSER")
        or candidate.get("proposer_kind")
    )
    proposal_date = clean(row.get("PROPOSE_DT") or row.get("PPSL_DT") or candidate.get("proposal_date"))
    return {
        **candidate,
        "bill_id": clean(row.get("BILL_ID") or candidate.get("bill_id")),
        "bill_no": clean(row.get("BILL_NO") or candidate.get("bill_no")),
        "bill_name": bill_name,
        "proposal_date": proposal_date,
        "proposer_kind": proposer,
        "detail_link": clean(row.get("DETAIL_LINK") or row.get("LINK_URL") or candidate.get("detail_link")),
        "relationship_source": "likms_alternative_info",
    }


def find_verified_successor_bill(
    session: requests.Session,
    original_entry: Dict,
    current_lifecycle: Dict,
) -> Optional[Dict]:
    """Resolve a committee alternative only from explicit official relationship evidence.

    Candidate generation remains broad and non-authoritative. Automatic succession occurs
    only when LIKMS' official alternative-information surface points to exactly one of those
    candidates, and that bill is then identity-verified against an Assembly API.
    """
    watched_law = clean(original_entry.get("matched_law"))
    original_bill_id = clean(original_entry.get("bill_id"))
    original_no = clean(original_entry.get("bill_no"))
    if not watched_law or not original_bill_id or not original_no:
        return None

    anchor = (
        monitor.parse_date(current_lifecycle.get("committee_process_date"))
        or monitor.parse_date(current_lifecycle.get("plenary_date"))
        or monitor.parse_date(original_entry.get("proposal_date"))
    )
    if not anchor:
        return None

    candidates = alternative_successor.fetch_candidate_alternatives(session, watched_law, anchor)
    candidates = [
        c for c in candidates
        if clean(c.get("bill_no")) and clean(c.get("bill_no")) != original_no
    ]
    if not candidates:
        print(f"[WARN] 대안 후보 없음: {original_no}")
        return None

    by_no = {clean(c.get("bill_no")): c for c in candidates}
    print(f"[INFO] 후보 전용 목록: {original_no} / {list(by_no)}")

    try:
        matched_nos, evidence_urls = likms_successor.fetch_likms_successor_bill_nos(
            session,
            original_bill_id,
            by_no.keys(),
        )
    except Exception as exc:
        print(f"[WARN] LIKMS 대안정보 관계조회 실패: {original_no} / {exc}")
        return None

    print(
        f"[INFO] LIKMS 대안정보 관계후보: {original_no} / {matched_nos or '-'} / "
        f"근거URL={evidence_urls}"
    )
    if len(matched_nos) != 1:
        print(
            f"[WARN] LIKMS 관계가 하나로 수렴하지 않아 자동승계 보류: "
            f"{original_no} / {matched_nos}"
        )
        return None

    successor_no = matched_nos[0]
    candidate = by_no[successor_no]
    if not likms_successor.validate_successor_candidate(candidate, watched_law):
        print(f"[WARN] LIKMS 도출 후보의 법률명/대안 정체성 불일치: {successor_no}")
        return None

    row = _exact_api_row(session, successor_no)
    if not row:
        print(f"[WARN] LIKMS 도출 대안을 국회 API에서 정확 재검증하지 못함: {successor_no}")
        return None

    merged = _merge_candidate_with_api(candidate, row)
    if not merged.get("bill_id"):
        print(f"[WARN] 후속 대안 BILL_ID 없음: {successor_no}")
        return None
    if monitor.match_watched_law(merged.get("bill_name")) != watched_law:
        print(f"[WARN] 후속 대안 법률명 불일치: {successor_no} / {merged.get('bill_name')}")
        return None
    if "대안" not in clean(merged.get("bill_name")) and "위원" not in clean(merged.get("proposer_kind")):
        print(f"[WARN] 후속 의안이 위원회 대안으로 검증되지 않음: {successor_no}")
        return None

    print(
        f"[PASS] 공식 대안관계 확정: {original_no} -> {successor_no} / "
        f"LIKM 대안정보 + 국회 API 정확일치"
    )
    return merged
