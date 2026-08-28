from typing import Dict, List, Optional

import requests

import alternative_successor
import likms_successor
import monitor
import status_monitor


def clean(value) -> str:
    return status_monitor.clean(value)


def _exact_api_row(session: requests.Session, bill_no: str) -> Optional[Dict]:
    lookup = {"bill_no": bill_no}
    for endpoint, include_age in [
        (monitor.MEMBER_BILLS_API, True),
        (status_monitor.PROCESSED_API, True),
    ]:
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


def _row_to_successor(row: Dict, relationship_source: str) -> Dict:
    return {
        "bill_id": clean(row.get("BILL_ID")),
        "bill_no": clean(row.get("BILL_NO")),
        "bill_name": clean(row.get("BILL_NAME") or row.get("BILL_NM")),
        "proposal_date": clean(row.get("PROPOSE_DT") or row.get("PPSL_DT")),
        "proposer_kind": clean(
            row.get("PPSR_KIND")
            or row.get("PROPOSER")
            or row.get("RST_PROPOSER")
            or row.get("PUBL_PROPOSER")
        ),
        "detail_link": clean(row.get("DETAIL_LINK") or row.get("LINK_URL")),
        "relationship_source": relationship_source,
    }


def _valid_relation_row(row: Dict, watched_law: str, original_no: str) -> bool:
    bill_no = clean(row.get("BILL_NO"))
    bill_name = clean(row.get("BILL_NAME") or row.get("BILL_NM"))
    proposer = clean(
        row.get("PPSR_KIND")
        or row.get("PROPOSER")
        or row.get("RST_PROPOSER")
        or row.get("PUBL_PROPOSER")
    )
    if not bill_no or bill_no == original_no:
        return False
    if monitor.match_watched_law(bill_name) != watched_law:
        return False
    return "대안" in bill_name or "위원" in proposer


def find_verified_successor_bill(
    session: requests.Session,
    original_entry: Dict,
    current_lifecycle: Dict,
) -> Optional[Dict]:
    """Resolve committee alternatives from explicit official relationship evidence.

    Priority:
    1. LIKMS 대안정보: direct relationship numbers.
    2. Exact Assembly API identity validation of every number returned by LIKMS.
    3. 국민참여입법센터 candidate discovery is auxiliary only and never sufficient.

    If the official relationship does not converge to exactly one validated bill,
    return None so production remains pending rather than risking a wrong successor.
    """
    watched_law = clean(original_entry.get("matched_law"))
    original_bill_id = clean(original_entry.get("bill_id"))
    original_no = clean(original_entry.get("bill_no"))
    if not watched_law or not original_bill_id or not original_no:
        return None

    try:
        relation_nos, evidence_urls = likms_successor.fetch_likms_successor_bill_nos(
            session,
            original_bill_id,
        )
    except Exception as exc:
        print(f"[WARN] LIKMS 대안정보 관계조회 실패: {original_no} / {exc}")
        return None

    print(
        f"[INFO] LIKMS 대안정보 원시 의안번호: {original_no} / {relation_nos or '-'} / "
        f"근거URL={evidence_urls}"
    )

    validated: List[Dict] = []
    for bill_no in relation_nos:
        if bill_no == original_no:
            continue
        row = _exact_api_row(session, bill_no)
        if not row:
            print(f"[INFO] LIKMS 관계번호 API 미확인으로 제외: {bill_no}")
            continue
        if not _valid_relation_row(row, watched_law, original_no):
            print(
                f"[INFO] LIKMS 관계번호 법률명/대안 정체성 불일치로 제외: "
                f"{bill_no} / {clean(row.get('BILL_NAME') or row.get('BILL_NM'))}"
            )
            continue
        validated.append(row)

    # Optional candidate-list corroboration. It must never create a successor by itself.
    anchor = (
        monitor.parse_date(current_lifecycle.get("committee_process_date"))
        or monitor.parse_date(current_lifecycle.get("plenary_date"))
        or monitor.parse_date(original_entry.get("proposal_date"))
    )
    candidate_nos = []
    if anchor:
        try:
            candidates = alternative_successor.fetch_candidate_alternatives(session, watched_law, anchor)
            candidate_nos = [clean(c.get("bill_no")) for c in candidates if clean(c.get("bill_no"))]
            print(f"[INFO] 보조 후보목록: {original_no} / {candidate_nos or '-'}")
        except Exception as exc:
            print(f"[WARN] 보조 후보목록 조회 실패(승계판정 영향 없음): {original_no} / {exc}")

    unique = {}
    for row in validated:
        unique[clean(row.get("BILL_NO"))] = row
    validated = list(unique.values())

    if len(validated) != 1:
        print(
            f"[WARN] LIKMS 공식관계가 하나의 검증된 대안으로 수렴하지 않음: "
            f"{original_no} / {[clean(r.get('BILL_NO')) for r in validated]}"
        )
        return None

    row = validated[0]
    successor = _row_to_successor(row, "likms_alternative_info")
    if not successor.get("bill_id"):
        print(f"[WARN] 후속 대안 BILL_ID 없음: {successor.get('bill_no')}")
        return None

    corroborated = successor.get("bill_no") in candidate_nos if candidate_nos else False
    print(
        f"[PASS] 공식 대안관계 확정: {original_no} -> {successor.get('bill_no')} / "
        f"LIKMS 대안정보 + 국회 API 정확일치 / 보조후보교차={corroborated}"
    )
    return successor
