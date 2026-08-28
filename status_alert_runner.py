import os
from datetime import datetime

import requests

import status_monitor
from alternative_successor import is_alternative_reflection_result
from post_plenary import fetch_post_plenary_status
from successor_operations import register_verified_successor
from successor_resolution import find_verified_successor_bill
from successor_state import escalation_due, mark_escalated, mark_pending

# 실제 알림은 핵심 단계만 사용한다.
status_monitor.MILESTONES = [
    ("committee_referral_date", "소관위원회 회부"),
    ("law_submit_date", "법제사법위원회 회부"),
    ("plenary_date", "본회의 처리"),
    ("government_transfer_date", "정부이송"),
]

_original_fetch_lifecycle = status_monitor.fetch_lifecycle
_original_highest_stage = status_monitor.highest_stage
_original_build_mail_html = status_monitor.build_mail_html


def fetch_lifecycle_with_transfer(session, bill_id, entry):
    current = _original_fetch_lifecycle(session, bill_id, entry) or {}
    try:
        post = fetch_post_plenary_status({**entry, "bill_id": bill_id}, session=session)
        if post.get("government_transfer_date"):
            current["government_transfer_date"] = post["government_transfer_date"]
    except Exception as exc:
        print(f"[WARN] 정부이송 조회 실패: {entry.get('bill_no') or bill_id} / {exc}")
    return current


def highest_stage_with_transfer(snapshot):
    if status_monitor.clean(snapshot.get("government_transfer_date")):
        return "정부이송"
    return _original_highest_stage(snapshot)


def build_mail_html_filtered(alerts):
    html = _original_build_mail_html(alerts)
    return html.replace(
        "소관위원회 회부·상정·처리, 법제사법위원회 진행, 본회의 처리 등 의미 있는 단계가 새로 확인될 때만 발송합니다.",
        "소관위원회 회부, 대안반영폐기·위원회 대안 승계, 법제사법위원회 회부, 본회의 처리, 정부이송의 핵심 단계가 새로 확인될 때만 발송합니다.",
    )


status_monitor.fetch_lifecycle = fetch_lifecycle_with_transfer
status_monitor.highest_stage = highest_stage_with_transfer
status_monitor.build_mail_html = build_mail_html_filtered


def _alternative_reflected(current_raw):
    return (
        is_alternative_reflection_result(current_raw.get("committee_process_result"))
        or is_alternative_reflection_result(current_raw.get("plenary_result"))
    )


def _first_successor_changes(current):
    """자동승계 의안의 첫 조회에서 이미 발생한 후속 핵심단계를 놓치지 않는다."""
    changes = []
    for field, label in [
        ("law_submit_date", "법제사법위원회 회부"),
        ("plenary_date", "본회의 처리"),
        ("government_transfer_date", "정부이송"),
    ]:
        value = status_monitor.clean(current.get(field))
        if value:
            changes.append({"field": field, "label": label, "old": "", "new": value})
    return changes


def _pending_change(first_notice: bool):
    if first_notice:
        return {
            "field": "alternative_successor_pending",
            "label": "대안반영폐기 → 공식 대안번호 확인 필요",
            "old": "",
            "new": "LIKMS 공식 관계 미확정 · 매일 재확인",
        }
    return None


def _escalation_change(entry, now):
    if not escalation_due(entry, now):
        return None
    mark_escalated(entry, now)
    return {
        "field": "alternative_successor_unresolved_14d",
        "label": "대안반영폐기 후속대안 14일 미확정",
        "old": "공식 대안 연결 대기",
        "new": "14일 경과 · 공식 관계 계속 재확인",
    }


def main() -> int:
    seen = status_monitor.monitor.load_seen()
    if not seen:
        print("[INFO] 추적 중인 의안이 없습니다.")
        return 0

    force_test = os.getenv("FORCE_SEND_STATUS_TEST", "false").lower() == "true"
    session = requests.Session()
    session.headers.update(status_monitor.monitor.HEADERS)
    now = datetime.now(status_monitor.monitor.KST).isoformat(timespec="seconds")
    alerts = []

    try:
        # 실행 중 위원회 대안이 새로 seen에 추가될 수 있으므로 시작 시점 목록만 순회한다.
        for bill_id, entry in list(seen.items()):
            if entry.get("status_tracking") is False:
                print(f"[INFO] 상태추적 제외: {entry.get('bill_no') or bill_id}")
                continue

            current_raw = status_monitor.fetch_lifecycle(session, bill_id, entry)
            if not current_raw:
                print(f"[WARN] 상태조회 실패/데이터 없음: {entry.get('bill_no') or bill_id}")
                continue

            previous = entry.get("lifecycle") if isinstance(entry.get("lifecycle"), dict) else {}
            current = status_monitor.merge_snapshot(previous, current_raw)
            changes = status_monitor.detect_changes(previous, current) if previous else []

            # 이미 후속 대안으로 승계된 원의안은 상태만 갱신하고 이후 단계 알림은 보내지 않는다.
            # 이후 알림은 successor 의안번호를 기준으로만 이어간다.
            if entry.get("alternative_reflection"):
                changes = []
                print(
                    f"[INFO] 승계 완료 원의안 상태알림 억제: {entry.get('bill_no')} → "
                    f"{entry.get('tracking_continued_as') or entry.get('successor_bill_no') or '-'}"
                )

            # 대안반영폐기 감지 → LIKMS의 명시적 selRefBillId 관계를 국회 API로
            # 정확 재검증한 경우에만 위원회 대안으로 자동승계한다.
            # status_tracking=true인 원 의안만 이 경로에 들어오므로 제외된 의안은 승계하지 않는다.
            elif _alternative_reflected(current_raw):
                entry["status"] = "대안반영폐기"
                try:
                    successor = find_verified_successor_bill(session, entry, current_raw)
                except Exception as exc:
                    successor = None
                    print(f"[WARN] 공식 위원회 대안 관계조회 실패: {entry.get('bill_no') or bill_id} / {exc}")

                if successor:
                    successor_entry, should_alert = register_verified_successor(
                        seen, bill_id, entry, successor, now
                    )
                    successor_no = successor_entry.get("bill_no") or successor.get("bill_no")
                    successor_name = successor_entry.get("bill_name") or successor.get("bill_name")
                    # 대안반영폐기 시점에는 원의안의 다른 단계변경보다 승계 이벤트만 알린다.
                    changes = []
                    if should_alert:
                        changes.append({
                            "field": "alternative_successor",
                            "label": "대안반영폐기 → 위원회 대안 자동승계",
                            "old": "",
                            "new": f"의안번호 {successor_no} · {successor_name}",
                        })
                    print(
                        f"[INFO] 위원회 대안 자동승계: {entry.get('bill_no')} → "
                        f"{successor_no} / {successor_name} / alert={should_alert}"
                    )
                else:
                    first_notice = mark_pending(entry, now)
                    pending_change = _pending_change(first_notice)
                    escalation_change = _escalation_change(entry, now)
                    # pending 상태에서는 원의안의 일반 단계변경 대신 해결상태만 알린다.
                    changes = []
                    if pending_change:
                        changes.append(pending_change)
                    if escalation_change:
                        changes.append(escalation_change)
                    print(
                        f"[WARN] 대안반영폐기 감지했으나 공식 후속 대안 미확정: "
                        f"{entry.get('bill_no')} / first_notice={first_notice}"
                    )

            # 과거 의안이 앞으로 정부이송 단계에서 처음 발견된 경우 그 이벤트만 1회 알림한다.
            if not previous and entry.get("late_stage_discovered_event") == "정부이송":
                transfer_date = current.get("government_transfer_date")
                if transfer_date:
                    changes = [{
                        "field": "government_transfer_date",
                        "label": "정부이송",
                        "old": "",
                        "new": transfer_date,
                    }] + [
                        c for c in changes
                        if c.get("field") in {
                            "alternative_successor",
                            "alternative_successor_pending",
                            "alternative_successor_unresolved_14d",
                        }
                    ]

            # 자동승계된 위원회 대안은 첫 조회에서도 이미 진행된 후속 핵심단계를 알린다.
            if not previous and entry.get("successor_tracking_started_at"):
                changes = _first_successor_changes(current) + changes
                entry.pop("successor_tracking_started_at", None)

            entry["lifecycle"] = current
            entry["last_status_checked_at"] = now
            if not entry.get("lifecycle_initialized_at"):
                entry["lifecycle_initialized_at"] = now

            if changes:
                alerts.append(
                    {
                        **entry,
                        "bill_id": bill_id,
                        "committee": current.get("committee"),
                        "detail_link": current.get("detail_link"),
                        "stage": (
                            "위원회 대안 자동승계"
                            if any(c.get("field") == "alternative_successor" for c in changes)
                            else "공식 대안번호 확인 필요"
                            if any(c.get("field") == "alternative_successor_pending" for c in changes)
                            else "후속대안 14일 미확정"
                            if any(c.get("field") == "alternative_successor_unresolved_14d" for c in changes)
                            else status_monitor.highest_stage(current)
                        ),
                        "changes": changes,
                    }
                )
                entry["last_status_changed_at"] = now
                entry.pop("late_stage_discovered_event", None)
                print(
                    f"[INFO] 상태변경 감지: {entry.get('bill_no')} / "
                    f"{status_monitor.highest_stage(current)} / {len(changes)}개"
                )
            elif force_test:
                alerts.append(
                    {
                        **entry,
                        "bill_id": bill_id,
                        "committee": current.get("committee"),
                        "detail_link": current.get("detail_link"),
                        "stage": status_monitor.highest_stage(current),
                        "changes": [],
                        "test_mode": True,
                    }
                )
                print(
                    f"[INFO] 테스트 대상: {entry.get('bill_no')} / "
                    f"현재 단계 {status_monitor.highest_stage(current)}"
                )

        status_monitor.monitor.save_seen(seen)

        if not alerts:
            print("[INFO] 기존 의안 상태변경 없음: 메일을 발송하지 않습니다.")
            return 0

        status_monitor.send_email(alerts)
        if force_test and all(alert.get("test_mode") for alert in alerts):
            print(f"[INFO] 상태변경 테스트 메일 발송 완료: {len(alerts)}건")
        else:
            print(f"[INFO] 상태변경 메일 발송 완료: {len(alerts)}건")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
