import html
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

import content_enrichment
import enriched_runner
import law_effective_monitor
import monitor
import status_monitor
import telegram_notify


def required_env(name: str) -> str:
    value = str(os.getenv(name) or "").strip()
    if not value:
        raise ValueError(f"필수 환경변수가 없습니다: {name}")
    return value


def send_html_email(subject: str, body: str) -> None:
    user = required_env("GMAIL_USER")
    password = required_env("GMAIL_APP_PASSWORD")
    target = required_env("MAIL_TO")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = target
    msg.attach(MIMEText(body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.sendmail(user, [target], msg.as_string())


def find_bill(bill_no: str):
    seen = monitor.load_seen()
    for bill_id, entry in seen.items():
        if str(entry.get("bill_no") or "").strip() == bill_no:
            return bill_id, dict(entry)
    raise ValueError(f"seen_bills.json에서 의안번호 {bill_no}를 찾지 못했습니다.")


def test_telegram_new(bill):
    original = telegram_notify._send
    def tagged(text):
        text = text.replace(
            "🏛️ <b>[국회 법률안] 신규</b>",
            "🧪 <b>[TEST] [국회 법률안] 신규</b>",
            1,
        )
        original(text)
    telegram_notify._send = tagged
    try:
        telegram_notify.send_new_bills([bill])
    finally:
        telegram_notify._send = original


def test_telegram_status(alert):
    original = telegram_notify._send
    def tagged(text):
        text = text.replace(
            "🔔 <b>[국회 법률안] 상태변경</b>",
            "🧪 <b>[TEST] [국회 법률안] 상태변경</b>",
            1,
        )
        original(text)
    telegram_notify._send = tagged
    try:
        telegram_notify.send_status_alerts([alert])
    finally:
        telegram_notify._send = original


def send_new_test(bill):
    content_enrichment.enrich_bills([bill])
    subject = "[TEST] " + enriched_runner.build_subject([bill])
    send_html_email(subject, enriched_runner.build_mail_html_enriched([bill]))
    test_telegram_new(bill)
    print("[PASS] 신규 발의 알림: 이메일 + Telegram")


def send_status_test(base, label: str, field: str, value: str, stage: str):
    alert = {
        **base,
        "committee": base.get("committee") or "정무위원회",
        "stage": stage,
        "changes": [{"field": field, "label": label, "old": "", "new": value}],
        "test_mode": False,
    }
    subject = "[TEST] " + status_monitor.build_subject([alert])
    send_html_email(subject, status_monitor.build_mail_html([alert]))
    test_telegram_status(alert)
    print(f"[PASS] {label} 알림: 이메일 + Telegram")


def main() -> int:
    bill_no = str(os.getenv("TEST_BILL_NO") or "2220774").strip()
    bill_id, entry = find_bill(bill_no)
    if entry.get("status_tracking") is False:
        raise RuntimeError(
            f"의안번호 {bill_no}는 status_tracking=false입니다. 실제 운영에서도 후속 알림 대상이 아닙니다."
        )

    detail_link = ""
    if isinstance(entry.get("lifecycle"), dict):
        detail_link = entry["lifecycle"].get("detail_link") or ""

    bill = {
        **entry,
        "bill_id": bill_id,
        "bill_no": bill_no,
        "detail_link": detail_link,
        "proposer": "유동수의원 등 10인" if bill_no == "2220774" else entry.get("proposer"),
        "committee": (entry.get("lifecycle") or {}).get("committee") or "미정/확인 전",
        "process_result": "발의",
    }

    print(f"[INFO] 전체 알림 테스트 시작: {bill_no} / {entry.get('bill_name')}")
    print("[INFO] 운영 seen_bills.json은 수정하지 않습니다.")

    send_new_test(bill)

    base = {
        **bill,
        "matched_law": entry.get("matched_law"),
        "proposal_date": entry.get("proposal_date"),
        "detail_link": detail_link,
    }
    send_status_test(base, "소관위원회 회부", "committee_referral_date", "2026-08-27", "소관위원회 회부")
    send_status_test(base, "법제사법위원회 회부", "law_submit_date", "2026-09-03", "법제사법위원회 회부")
    send_status_test(base, "본회의 처리", "plenary_date", "2026-09-10", "본회의 처리")
    send_status_test(base, "정부이송", "government_transfer_date", "2026-09-14", "정부이송")

    record = {
        "law_name": entry.get("matched_law"),
        "promulgation_date": "2026-09-20",
        "enforcement_date": "2027-03-20",
        "promulgation_no": "99999",
        "revision_type": "일부개정",
        "detail_link": "https://www.law.go.kr",
    }
    law_effective_monitor.send_promulgation(record, test_mode=True)
    print("[PASS] 공포 알림: 이메일 + Telegram")
    law_effective_monitor.send_enforcement(record, test_mode=True, today="20270320")
    print("[PASS] 시행 알림: 이메일 + Telegram")

    print("[PASS] 전체 알림 체인 완료: 신규 → 소관위 → 법사위 → 본회의 → 정부이송 → 공포 → 시행")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
