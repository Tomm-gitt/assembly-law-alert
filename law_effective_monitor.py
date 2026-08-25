import html
import json
import os
import re
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List

import requests

import monitor
from telegram_notify import _send as telegram_send

LAW_API_URL = "https://www.law.go.kr/DRF/lawSearch.do"
STATE_PATH = Path("law_effective_state.json")

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


def law_link(value: str) -> str:
    value = clean(value)
    if not value:
        return "https://www.law.go.kr"
    if value.startswith("http://"):
        return "https://" + value[len("http://"):]
    if value.startswith("https://"):
        return value
    if value.startswith("/"):
        return "https://www.law.go.kr" + value
    return "https://www.law.go.kr/" + value


def load_state() -> Dict:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state: Dict) -> None:
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
                "detail_link": law_link(item.get("법령상세링크")),
            }
        )

    unique = {}
    for row in rows:
        key = f"{row['promulgation_date']}:{row['promulgation_no']}"
        unique[key] = row
    return sorted(unique.values(), key=lambda x: (x["promulgation_date"], x["promulgation_no"]), reverse=True)


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
        <div style="margin-top:18px;"><a href="{html.escape(law_link(record.get('detail_link')), quote=True)}" style="color:#1a73e8;text-decoration:none;font-weight:600;">국가법령정보센터 보기 →</a></div>
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
        <div style="margin-top:18px;"><a href="{html.escape(law_link(record.get('detail_link')), quote=True)}" style="color:#1a73e8;text-decoration:none;font-weight:600;">국가법령정보센터 보기 →</a></div>
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
        f'<a href="{html.escape(law_link(record.get("detail_link")), quote=True)}">국가법령정보센터 →</a>'
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
        f'<a href="{html.escape(law_link(record.get("detail_link")), quote=True)}">국가법령정보센터 →</a>'
    )
    telegram_send(text)


def main() -> int:
    oc = clean(os.getenv("LAW_API_OC"))
    if not oc:
        print("[WARN] LAW_API_OC Secret이 없어 공포·시행 자동추적을 건너뜁니다.")
        return 0

    today = datetime.now(monitor.KST).strftime("%Y%m%d")
    state = load_state()
    first_run = not bool(state)
    now = datetime.now(monitor.KST).isoformat(timespec="seconds")
    session = requests.Session()
    session.headers.update(monitor.HEADERS)

    try:
        for law_name in monitor.WATCH_LAWS:
            versions = fetch_versions(session, law_name, oc)
            if not versions:
                print(f"[WARN] 법제처 검색결과 없음: {law_name}")
                continue

            law_state = state.setdefault(law_name, {})
            records = law_state.setdefault("records", {})

            for record in versions:
                key = f"{record['promulgation_date']}:{record['promulgation_no']}"
                existing = records.get(key)
                if existing is None:
                    existing = {
                        **record,
                        "first_seen_at": now,
                        "promulgation_sent": first_run,
                        "enforcement_sent": bool(record.get("enforcement_date") and record["enforcement_date"] < today),
                    }
                    records[key] = existing
                    if not first_run:
                        send_promulgation(existing)
                        existing["promulgation_sent"] = True
                        existing["promulgation_sent_at"] = now
                        print(f"[INFO] 공포 알림 발송: {law_name} / 제{record['promulgation_no']}호")
                else:
                    existing.update({k: v for k, v in record.items() if v})

                enforcement_date = clean(existing.get("enforcement_date"))
                if enforcement_date and enforcement_date <= today and not existing.get("enforcement_sent"):
                    send_enforcement(existing, today=today)
                    existing["enforcement_sent"] = True
                    existing["enforcement_sent_at"] = now
                    print(f"[INFO] 시행 알림 발송: {law_name} / {fmt_date(enforcement_date)}")

            law_state["last_checked_at"] = now

        save_state(state)
        if first_run:
            print("[INFO] 공포·시행 최초 실행: 기존 공포 이력은 기준 데이터로 저장하고 과거 공포 메일은 발송하지 않습니다.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
