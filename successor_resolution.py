from typing import Dict, List, Optional

import requests

import alternative_successor
import likms_successor
import monitor
import status_monitor


def clean(value) -> str:
    return status_monitor.clean(value)


def _exact_api_row_by_id(session: requests.Session, bill_id: str) -> Optional[Dict]:
    lookup = {"bill_id": bill_id}
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
            print(f"[WARN] 후속대안 국회 API BILL_ID 검증 실패: {endpoint} / {bill_id} / {exc}")
            continue
        if row and clean(row.get("BILL_ID")) == bill_id:
            return row
    return None


def _row_to_successor(row: Dict) -> Dict:
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
        "relationship_source": "likms_selRefBillId",
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
    watched_law = clean(original_entry.get("matched_law"))
    original_bill_id = clean(original_entry.get("bill_id"))
    original_no = clean(original_entry.get("bill_no"))
    if not watched_law or not original_bill_id or not original_no:
        return None

    try:
        relation_ids, evidence_urls = likms_successor.fetch_likms_successor_bill_ids(
            session,
            original_bill_id,
        )
    except Exception as exc:
        print(f"[WARN] LIKMS selRefBillId 관계조회 실패: {original_no} / {exc}")
        return None

    print(
        f"[INFO] LIKMS 공식 참조 BILL_ID: {original_no} / {relation_ids or '-'} / "
        f"근거URL={evidence_urls}"
    )

    validated: List[Dict] = []
    for relation_id in relation_ids:
        row = _exact_api_row_by_id(session, relation_id)
        if not row:
            print(f"[INFO] LIKMS 참조 BILL_ID API 미확인으로 제외: {relation_id}")
            continue
        if not _valid_relation_row(row, watched_law, original_no):
            print(
                f"[INFO] LIKMS 참조 BILL_ID 법률명/대안 정체성 불일치로 제외: "
                f"{relation_id} / {clean(row.get('BILL_NAME') or row.get('BILL_NM'))}"
            )
            continue
        validated.append(row)

    if len(validated) != 1:
        print(
            f"[WARN] LIKMS 공식관계가 하나의 검증된 대안으로 수렴하지 않음: "
            f"{original_no} / {[clean(r.get('BILL_NO')) for r in validated]}"
        )
        return None

    successor = _row_to_successor(validated[0])

    # Candidate discovery is now only a non-blocking corroboration signal.
    corroborated = False
    anchor = (
        monitor.parse_date(current_lifecycle.get("committee_process_date"))
        or monitor.parse_date(current_lifecycle.get("plenary_date"))
        or monitor.parse_date(original_entry.get("proposal_date"))
    )
    if anchor:
        try:
            candidates = alternative_successor.fetch_candidate_alternatives(session, watched_law, anchor)
            candidate_nos = [clean(c.get("bill_no")) for c in candidates if clean(c.get("bill_no"))]
            corroborated = successor.get("bill_no") in candidate_nos
            print(f"[INFO] 보조 후보교차: {original_no} / {candidate_nos or '-'} / match={corroborated}")
        except Exception as exc:
            print(f"[WARN] 보조 후보목록 조회 실패(승계판정 영향 없음): {original_no} / {exc}")

    print(
        f"[PASS] 공식 대안관계 확정: {original_no} -> {successor.get('bill_no')} / "
        f"LIKMS selRefBillId + 국회 API BILL_ID 정확일치 / 보조후보교차={corroborated}"
    )
    return successor
