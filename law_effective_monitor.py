import html
import os
import re
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List
from urllib.parse import quote

import requests

import monitor
from post_plenary import fetch_post_plenary_status
from telegram_notify import _send as telegram_send

LAW_API_URL = "https://www.law.go.kr/DRF/lawSearch.do"

LAW_SUBJECT_KEYWORDS = {
    "식품위생법": "식품위생",
    "건강기능식품에 관한 법률": "건강기능식품",
    "식품 등의 표시·광고에 관한 법률": "식품표시광고",
    "제조물 책임법": "제조물책임",
    "자원의 절약과 재활용촉진에 관한 법률": "자원재활용",
    "농수산물의 원산지 표시 등에 관한 법률": "원산지표시",
    "독점규제 및 공정거래에 관한 법률": "공정거래",
    "가맹사업거래의 공정화에 관한 법률": "가맹사업",
    "약관의 규제에 관한 법률": "약관규제",
    "소비자기본법": "소비자기본",
    "하도급거래 공정화에 관한 법률": "하도급",
    "전자상거래 등에서의 소비자보호에 관한 법률": "전자상거래",
    "표시·광고의 공정화에 관한 법률": "표시광고",
    "인삼산업법": "인삼",
    "농수산물 품질관리법": "농수산물품질",
}


def clean(value) -> str:
    return str(value or "").strip()


def normalize(text: str) -> str:
    text = re.sub(r"\s+", "", clean(text))
    return re.sub(r"[ㆍ･•]", "·", text)


def fmt_date(value: str) -> str:
    digits = re.sub(r"\D", "", clean(value))
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return clean(value) or "-"


def date_digits(value: str) -> str:
    digits = re.sub(r"\D", "", clean(value))
    return digits[:8] if len(digits) >= 8 else ""


def public_law_link(record: Dict) -> str:
    law_name = clean(record.get("law_name"))
    if law_name:
        return f"https://www.law.go.kr/법령/{quote(law_name)}"
    return "https://www.law.go.kr"


def walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def fetch_versions(session: requests.Session, law_name: str, oc: str) -> List[Dict]:
    params = {
        "OC": oc,
        "target": "eflaw",
        "type": "JSON",
        "query": law_name,
        "nw": "1,2,3",
        "display": "30",
        "page": "1",
        "sort": "ddes",
    }
    response = session.get(LAW_API_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    rows = []
    target = normalize(law_name)
    for item in walk_dicts(data):
        row_name = clean(item.get("법령명한글") or item.get("법령명"))
        if not row_name or normalize(row_name) != target:
            continue
        promulgation_date = clean(item.get("공포일자"))
        promulgation_no = clean(item.get("공포번호"))
        enforcement_date = clean(item.get("시행일자"))
        if not promulgation_date or not promulgation_no:
            continue
        rows.append(
            {
                "law_name": row_name,
                "promulgation_date": date_digits(promulgation_date),
                "promulgation_no": promulgation_no,
                "enforcement_date": date_digits(enforcement_date),
                "revision_type": clean(item.get("제개정구분명")),
            }
        )

    unique = {}
    for row in rows:
        key = f"{row['promulgation_date']}:{row['promulgation_no']}"
        unique[key] = row
    return sorted(unique.values(), key=lambda x: (x["promulgation_date"], x["promulgation_no"]), reverse=True)


def verify_promulgation(session, oc: str, law_name: str, post: Dict) -> Dict:
    target_date = date_digits(post.get("promulgation_date"))
    target_no = re.sub(r"\D", "", clean(post.get("promulgation_no")))
    for record in fetch_versions(session, law_name, oc):
        record_no = re.sub(r"\D", "", clean(record.get("promulgation_no")))
        if record.get("promulgation_date") == target_date and record_no == target_no:
            record["detail_link"] = public_law_link(record)
            return record
    return {}


def keyword_for(law_name: str) -> str:
    return LAW_SUBJECT_KEYWORDS.get(law_name, law_name)


def display_title(record: Dict) -> str:
    law_name = clean(record.get("law_name"))
    revision = clean(record.get("revision_type"))
    if revision in {"일부개정", "전부개정", "제정"}:
        return f"{law_name} {revision}법률"
    return law_name


def build_promulgation_html(record: Dict, test_mode: bool = False) -> str:
    badge = "[TEST] " if test_mode else ""
    return f"""
    <html><body style="font-family:Arial,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;background:#f5f7fa;margin:0;">
      <div style="max-width:680px;margin:0 auto;padding:20px;"><div style="background:#fff;border-radius:12px;padding:24px;">
        <div style="font-size:13px;color:#6b7280;">{badge}법률 공포 알림</div>
        <div style="font-size:22px;font-weight:700;margin-top:6px;">📢 {html.escape(display_title(record))}</div>
        <div style="margin-top:18px;line-height:1.9;color:#374151;">
          <b>공포일</b> · {fmt_date(record.get('promulgation_date'))}<br>
          <b>시행일</b> · {fmt_date(record.get('enforcement_date'))}<br>
          <b>법률번호</b> · 제{html.escape(clean(record.get('promulgation_no')))}호
        </div>
        <div style="margin-top:18px;"><a href="{html.escape(public_law_link(record), quote=True)}" style="color:#1a73e8;text-decoration:none;font-weight:600;">국가법령정보센터 보기 →</a></div>
      </div></div>
    </body></html>
    """


def build_enforcement_html(record: Dict, test_mode: bool = False, today: str = "") -> str:
    badge = "[TEST] " if test_mode else ""
    enforcement = date_digits(record.get("enforcement_date"))
    today = today or datetime.now(monitor.KST).strftime("%Y%m%d")
    sentence = "오늘부터 시행됩니다." if enforcement == today else "시행되었습니다."
    return f"""
    <html><body style="font-family:Arial,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;background:#f5f7fa;margin:0;">
      <div style="max-width:680px;margin:0 auto;padding:20px;"><div style="background:#fff;border-radius:12px;padding:24px;">
        <div style="font-size:13px;color:#6b7280;">{badge}법률 시행 알림</div>
        <div style="font-size:22px;font-weight:700;margin-top:6px;">✅ {html.escape(display_title(record))}</div>
        <div style="margin-top:18px;font-size:16px;font-weight:700;">{sentence}</div>
        <div style="margin-top:10px;line-height:1.9;color:#374151;"><b>시행일</b> · {fmt_date(enforcement)}</div>
        <div style="margin-top:18px;"><a href="{html.escape(public_law_link(record), quote=True)}" style="color:#1a73e8;text-decoration:none;font-weight:600;">국가법령정보센터 보기 →</a></div>
      </div></div>
    </body></html>
    """


def send_email(subject: str, html_body: str) -> None:
    gmail_user = monitor.required_env("GMAIL_USER")
    gmail_password = monitor.required_env("GMAIL_APP_PASSWORD")
    mail_to = monitor.required_env("MAIL_TO")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = mail_to
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(gmail_user, gmail_password)
        smtp.sendmail(gmail_user, [mail_to], msg.as_string())


def send_promulgation(record: Dict, test_mode: bool = False) -> None:
    prefix = "[TEST] " if test_mode else ""
    subject = f"{prefix}[국회 법률안] 공포_{keyword_for(record['law_name'])}"
    send_email(subject, build_promulgation_html(record, test_mode))
    text = (
        f"📢 <b>{html.escape(subject)}</b>\n\n"
        f"<b>{html.escape(display_title(record))}</b>\n\n"
        f"• 공포일: {fmt_date(record.get('promulgation_date'))}\n"
        f"• 시행일: {fmt_date(record.get('enforcement_date'))}\n"
        f"• 법률번호: 제{html.escape(clean(record.get('promulgation_no')))}호\n\n"
        f'<a href="{html.escape(public_law_link(record), quote=True)}">국가법령정보센터 →</a>'
    )
    telegram_send(text)


def send_enforcement(record: Dict, test_mode: bool = False, today: str = "") -> None:
    prefix = "[TEST] " if test_mode else ""
    subject = f"{prefix}[법률 시행] {keyword_for(record['law_name'])}"
    today = today or datetime.now(monitor.KST).strftime("%Y%m%d")
    enforcement = date_digits(record.get("enforcement_date"))
    sentence = "오늘부터 시행됩니다." if enforcement == today else "시행되었습니다."
    send_email(subject, build_enforcement_html(record, test_mode, today))
    text = (
        f"✅ <b>{html.escape(subject)}</b>\n\n"
        f"<b>{html.escape(display_title(record))}</b>\n\n"
        f"{sentence}\n"
        f"• 시행일: {fmt_date(enforcement)}\n\n"
        f'<a href="{html.escape(public_law_link(record), quote=True)}">국가법령정보센터 →</a>'
    )
    telegram_send(text)


def main() -> int:
    oc = clean(os.getenv("LAW_API_OC"))
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
            verified = verify_promulgation(session, oc, law_name, post)
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
                send_promulgation(current)
                current["promulgation_sent"] = True
                current["promulgation_sent_at"] = now
                entry.pop("late_stage_discovered_event", None)
                print(f"[INFO] 공포 알림 발송: {entry.get('bill_no')} / 제{current.get('promulgation_no')}호")

            enforcement_date = clean(current.get("enforcement_date"))
            if enforcement_date and enforcement_date <= today and not current.get("enforcement_sent"):
                send_enforcement(current, today=today)
                current["enforcement_sent"] = True
                current["enforcement_sent_at"] = now
                print(f"[INFO] 시행 알림 발송: {entry.get('bill_no')} / {fmt_date(enforcement_date)}")

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
