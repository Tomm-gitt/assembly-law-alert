import os
from datetime import datetime

import requests

import status_monitor

# 메일 피로도를 줄이기 위해 실제 알림은 핵심 3단계만 사용한다.
status_monitor.MILESTONES = [
    ("committee_referral_date", "소관위원회 회부"),
    ("law_submit_date", "법제사법위원회 회부"),
    ("plenary_date", "본회의 처리"),
]

_original_build_mail_html = status_monitor.build_mail_html


def build_mail_html_filtered(alerts):
    html = _original_build_mail_html(alerts)
    return html.replace(
        "소관위원회 회부·상정·처리, 법제사법위원회 진행, 본회의 처리 등 의미 있는 단계가 새로 확인될 때만 발송합니다.",
        "소관위원회 회부, 법제사법위원회 회부, 본회의 처리의 3개 핵심 단계가 새로 확인될 때만 발송합니다.",
    )


status_monitor.build_mail_html = build_mail_html_filtered


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
        for bill_id, entry in seen.items():
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
                        "stage": status_monitor.highest_stage(current),
                        "changes": changes,
                    }
                )
                entry["last_status_changed_at"] = now
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
