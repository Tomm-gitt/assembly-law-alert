import os
from datetime import datetime

import requests

import status_monitor
from alternative_successor import (
    is_alternative_reflection_result,
    register_successor,
)
from post_plenary import fetch_post_plenary_status
from successor_resolution import find_verified_successor_bill

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

            # 대안반영폐기 감지 → LIKMS의 명시적 selRefBillId 관계를 국회 API로
            # 정확 재검증한 경우에만 위원회 대안으로 자동승계한다.
            # 동일 법률·시기 후보탐색은 보조 교차검증일 뿐 자동승계 근거가 아니다.
            # status_tracking=true인 원 의안만 이 경로에 들어오므로 제외된 의안은 승계하지 않는다.
            if _alternative_reflected(current_raw) and not entry.get("alternative_reflection"):
                try:
                    successor = find_verified_successor_bill(session, entry, current_raw)
                except Exception as exc:
                    successor = None
                    print(f"[WARN] 공식 위원회 대안 관계조회 실패: {entry.get('bill_no') or bill_id} / {exc}")

                if successor:
                    successor_entry = register_successor(seen, bill_id, entry, successor, now)
                    successor_no = successor_entry.get("bill_no") or successor.get("bill_no")
                    successor_name = successor_entry.get("bill_name") or successor.get("bill_name")
                    changes.append({
                        "field": "alternative_successor",
                        "label": "대안반영폐기 → 위원회 대안 자동승계",
                        "old": "",
                        "new": f"의안번호 {successor_no} · {successor_name}",
                    })
                    print(
                        f"[INFO] 위원회 대안 자동승계: {entry.get('bill_no')} → "
                        f"{successor_no} / {successor_name}"
                    )
                else:
                    entry["alternative_successor_pending"] = True
                    entry["alternative_successor_last_checked_at"] = now
                    print(f"[WARN] 대안반영폐기 감지했으나 공식 후속 대안 미확정: {entry.get('bill_no')}")

            # 이전 실행에서 대안이 아직 확인되지 않았다면 매일 LIKMS 공식관계를 다시 확인한다.
            elif entry.get("alternative_successor_pending") and not entry.get("alternative_reflection"):
                try:
                    successor = find_verified_successor_bill(session, entry, current_raw)
                except Exception as exc:
                    successor = None
                    print(f"[WARN] 공식 위원회 대안 관계 재조회 실패: {entry.get('bill_no') or bill_id} / {exc}")
                entry["alternative_successor_last_checked_at"] = now
                if successor:
                    successor_entry = register_successor(seen, bill_id, entry, successor, now)
                    entry.pop("alternative_successor_pending", None)
                    successor_no = successor_entry.get("bill_no") or successor.get("bill_no")
                    successor_name = successor_entry.get("bill_name") or successor.get("bill_name")
                    changes.append({
                        "field": "alternative_successor",
                        "label": "위원회 대안 자동승계",
                        "old": "대안 연결 대기",
                        "new": f"의안번호 {successor_no} · {successor_name}",
                    })
                    print(f"[INFO] 위원회 대안 공식관계 재확인 성공: {entry.get('bill_no')} → {successor_no}")

            # 과거 의안이 앞으로 정부이송 단계에서 처음 발견된 경우 그 이벤트만 1회 알림한다.
            if not previous and entry.get("late_stage_discovered_event") == "정부이송":
                transfer_date = current.get("government_transfer_date")
                if transfer_date:
                    changes = [{
                        "field": "government_transfer_date",
                        "label": "정부이송",
                        "old": "",
                        "new": transfer_date,
                    }] + [c for c in changes if c.get("field") == "alternative_successor"]

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
