from datetime import datetime, timedelta
from typing import Dict, Optional

PENDING_ESCALATION_DAYS = 14


def _parse_iso(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def mark_pending(entry: Dict, now: str) -> bool:
    """Mark unresolved successor state. Return True only for the first user-facing notice."""
    first_notice = not entry.get("successor_resolution_pending_since")
    entry["successor_resolution_status"] = "pending"
    entry["alternative_successor_pending"] = True  # backward-compatible flag
    entry["alternative_successor_last_checked_at"] = now
    if first_notice:
        entry["successor_resolution_pending_since"] = now
        entry["successor_resolution_pending_notice_sent_at"] = now
    return first_notice


def escalation_due(entry: Dict, now: str) -> bool:
    if entry.get("successor_resolution_status") != "pending" and not entry.get("alternative_successor_pending"):
        return False
    if entry.get("successor_resolution_14d_alerted_at"):
        return False
    started = _parse_iso(entry.get("successor_resolution_pending_since"))
    current = _parse_iso(now)
    if not started or not current:
        return False
    return current >= started + timedelta(days=PENDING_ESCALATION_DAYS)


def mark_escalated(entry: Dict, now: str) -> None:
    entry["successor_resolution_14d_alerted_at"] = now


def clear_pending(entry: Dict) -> None:
    entry.pop("alternative_successor_pending", None)
    entry.pop("successor_resolution_pending_since", None)
    entry.pop("successor_resolution_pending_notice_sent_at", None)
    entry.pop("successor_resolution_14d_alerted_at", None)
