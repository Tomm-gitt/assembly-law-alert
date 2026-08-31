import re
import sys
from datetime import datetime

import requests

import hub_notify
import law_effective_monitor as lem
import monitor
from post_plenary import fetch_post_plenary_status


def clean(value) -> str:
    return str(value or "").strip()


def _hub_alert(entry, bill_id, stage, record):
    return {
        **entry,
        "bill_id": bill_id,
        "hub_source_id": clean(entry.get("hub_source_id") or bill_id),
        "bill_name": clean(entry.get("bill_name")) or lem.display_title(record),
        "bill_no": clean(entry.get("bill_no")),
        "proposal_date": clean(entry.get("proposal_date")),
        "detail_link": clean(record.get("detail_link")) or lem.public_law_link(record),
        "matched_law": clean(entry.get("matched_law")) or clean(record.get("law_name")),
        "committee": clean(entry.get("committee")),
        "stage": stage,
        "promulgation_date": clean(record.get("promulgation_date")),
        "promulgation_no": clean(record.get("promulgation_no")),
        "enforcement_date": clean(record.get("enforcement_date")),
    }


def send_promulgation_via_hub(entry, bill_id, record):
    subject = f"[국회 법률안] 공포_{lem.keyword_for(record['law_name'])}"
    lem.send_email(subject, lem.build_promulgation_html(record))
    eligible = hub_notify.send_status_alerts([_hub_alert(entry, bill_id, "공포", record)])
    if not eligible:
        raise RuntimeError("허브가 공포 알림을 추적중단 처리했습니다.")


def send_enforcement_via_hub(entry, bill_id, record, today):
    subject = f"[법률 시행] {lem.keyword_for(record['law_name'])}"
    lem.send_email(subject, lem.build_enforcement_html(record, today=today))
    eligible = hub_notify.send_status_alerts([_hub_alert(entry, bill_id, "시행", record)])
    if not eligible:
        raise RuntimeError("허브가 시행 알림을 추적중단 처리했습니다.")


def main() -> int:
    oc = clean(lem.os.getenv("LAW_API_OC"))
    if not oc:
        print("[WARN] LAW_API_OC Secret이 없어 공포·시행 자동추적을 건너뜁니다.")
        return 0

    seen = monitor.load_seen()
    if not seen:
        print("[INFO] 추적 중인 의안이 없어 공포·시행 조회를 건너뜁니다.")
        return 0

    today = datetime.now(monitor.KST).strftime("%Y%m%d")
    now = datetime.now(monitor.KST).isoformat(timespec="seconds")
    session = requests.Session()
    session.headers.update(monitor.HEADERS)

    try:
        for bill_id, entry in seen.items():
            if entry.get("status_tracking") is False:
                print(f"[INFO] 공포·시행 추적 제외: {entry.get('bill_no') or bill_id}")
                continue

            initializing = not bool(entry.get("post_plenary_master_initialized_at"))
            try:
                post = fetch_post_plenary_status(entry, session=session)
            except Exception as exc:
                print(f"[WARN] 공포정보 조회 실패: {entry.get('bill_no') or bill_id} / {exc}")
                continue

            entry["post_plenary_master_initialized_at"] = entry.get("post_plenary_master_initialized_at") or now
            if not post.get("promulgation_date") or not post.get("promulgation_no"):
                continue

            law_name = clean(entry.get("matched_law"))
            verified = lem.verify_promulgation(session, oc, law_name, post)
            if not verified:
                print(
                    f"[WARN] 법제처 검증 대기: {entry.get('bill_no')} / "
                    f"공포 {post.get('promulgation_date')} 제{post.get('promulgation_no')}호"
                )
                continue

            current = entry.get("promulgation") if isinstance(entry.get("promulgation"), dict) else {}
            same_publication = (
                clean(current.get("promulgation_date")) == clean(verified.get("promulgation_date"))
                and re.sub(r"\D", "", clean(current.get("promulgation_no")))
                == re.sub(r"\D", "", clean(verified.get("promulgation_no")))
            )

            if not same_publication:
                baseline_only = initializing and entry.get("late_stage_discovered_event") != "공포"
                current = {
                    **verified,
                    "verified_at": now,
                    "promulgation_sent": baseline_only,
                    "enforcement_sent": bool(
                        verified.get("enforcement_date") and verified["enforcement_date"] < today
                    ),
                }
                entry["promulgation"] = current
                if baseline_only:
                    print(f"[INFO] 기존 공포정보 기준 저장: {entry.get('bill_no')} / 제{verified.get('promulgation_no')}호")

            if not current.get("promulgation_sent"):
                send_promulgation_via_hub(entry, bill_id, current)
                current["promulgation_sent"] = True
                current["promulgation_sent_at"] = now
                entry.pop("late_stage_discovered_event", None)
                print(f"[INFO] 허브 공포 알림 처리: {entry.get('bill_no')} / 제{current.get('promulgation_no')}호")

            enforcement_date = clean(current.get("enforcement_date"))
            if enforcement_date and enforcement_date <= today and not current.get("enforcement_sent"):
                send_enforcement_via_hub(entry, bill_id, current, today)
                current["enforcement_sent"] = True
                current["enforcement_sent_at"] = now
                print(f"[INFO] 허브 시행 알림 처리: {entry.get('bill_no')} / {lem.fmt_date(enforcement_date)}")

        monitor.save_seen(seen)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
