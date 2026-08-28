from copy import deepcopy

from successor_operations import register_verified_successor
from successor_state import escalation_due, mark_escalated, mark_pending

NOW = "2026-08-28T10:00:00+09:00"


def origin(no):
    return {
        "bill_no": no,
        "bill_name": "소비자기본법 일부개정법률안",
        "matched_law": "소비자기본법",
        "status_tracking": True,
    }


def successor():
    return {
        "bill_id": "SUCCESSOR-ID",
        "bill_no": "2299999",
        "bill_name": "소비자기본법 일부개정법률안(대안)",
        "proposal_date": "2026-08-28",
        "relationship_source": "likms_selRefBillId",
    }


def test_pending_notice_and_escalation_once():
    entry = origin("2200001")
    assert mark_pending(entry, NOW) is True
    assert entry["successor_resolution_status"] == "pending"
    assert mark_pending(entry, "2026-08-29T10:00:00+09:00") is False
    assert escalation_due(entry, "2026-09-10T09:59:59+09:00") is False
    assert escalation_due(entry, "2026-09-11T10:00:00+09:00") is True
    mark_escalated(entry, "2026-09-11T10:00:00+09:00")
    assert escalation_due(entry, "2026-09-12T10:00:00+09:00") is False


def test_multiple_origins_one_successor_one_transition_alert():
    seen = {}
    first = origin("2200001")
    second = origin("2200002")
    succ = successor()

    first_entry, first_alert = register_verified_successor(seen, "ORIGIN-1", first, succ, NOW)
    second_entry, second_alert = register_verified_successor(
        seen, "ORIGIN-2", second, succ, "2026-08-28T10:01:00+09:00"
    )

    assert first_entry is second_entry
    assert first_alert is True
    assert second_alert is False
    assert first_entry["origin_bill_nos"] == ["2200001", "2200002"]
    assert first["tracking_continued_as"] == "2299999"
    assert second["tracking_continued_as"] == "2299999"
    assert first["successor_resolution_status"] == "resolved"
    assert second["successor_resolution_status"] == "resolved"


def test_existing_manual_false_successor_stays_false():
    seen = {
        "SUCCESSOR-ID": {
            "bill_no": "2299999",
            "bill_name": "소비자기본법 일부개정법률안(대안)",
            "status_tracking": False,
            "origin_bill_nos": [],
        }
    }
    entry = origin("2200001")
    resolved, _ = register_verified_successor(seen, "ORIGIN-1", entry, successor(), NOW)
    assert resolved["status_tracking"] is False


def test_idempotent_rerun_does_not_duplicate_origin_or_alert():
    seen = {}
    entry = origin("2200001")
    succ = successor()
    _, first_alert = register_verified_successor(seen, "ORIGIN-1", entry, succ, NOW)
    snapshot = deepcopy(seen["SUCCESSOR-ID"]["origin_bill_nos"])
    _, second_alert = register_verified_successor(
        seen, "ORIGIN-1", entry, succ, "2026-08-28T11:00:00+09:00"
    )
    assert first_alert is True
    assert second_alert is False
    assert seen["SUCCESSOR-ID"]["origin_bill_nos"] == snapshot == ["2200001"]


def main():
    test_pending_notice_and_escalation_once()
    test_multiple_origins_one_successor_one_transition_alert()
    test_existing_manual_false_successor_stays_false()
    test_idempotent_rerun_does_not_duplicate_origin_or_alert()
    print("[SUCCESS] successor state safety regression tests passed")


if __name__ == "__main__":
    main()
