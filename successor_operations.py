from typing import Dict, Tuple

from alternative_successor import register_successor
from successor_state import clear_pending


def register_verified_successor(
    seen: Dict[str, Dict],
    original_bill_id: str,
    original_entry: Dict,
    successor: Dict,
    now: str,
) -> Tuple[Dict, bool]:
    """Register a verified LIKMS successor and return (successor_entry, should_alert).

    A successor transition is announced only once globally even when multiple
    origin bills are merged into the same committee alternative.

    The central hub must keep the original O/X judgment across a committee
    alternative transition. Therefore the successor inherits the original
    hub identity instead of creating a fresh hub judgment record.
    """
    successor_entry = register_successor(seen, original_bill_id, original_entry, successor, now)
    successor_no = str(successor_entry.get("bill_no") or successor.get("bill_no") or "").strip()

    inherited_hub_source_id = str(
        original_entry.get("hub_source_id") or original_bill_id or ""
    ).strip()
    if inherited_hub_source_id:
        successor_entry["hub_source_id"] = inherited_hub_source_id
        original_entry["hub_source_id"] = inherited_hub_source_id

    original_entry["successor_resolution_status"] = "resolved"
    original_entry["successor_bill_no"] = successor_no
    original_entry["successor_evidence_source"] = str(successor.get("relationship_source") or "likms_selRefBillId")
    original_entry["successor_resolved_at"] = now
    clear_pending(original_entry)

    already_announced = bool(successor_entry.get("succession_transition_announced_at"))
    if not already_announced:
        successor_entry["succession_transition_announced_at"] = now
    return successor_entry, not already_announced
