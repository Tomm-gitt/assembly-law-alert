import html
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional, Tuple

import requests

import monitor

JUDGE_API = "BILLJUDGE"
PROCESSED_API = "nzpltgfqabtcpsmai"

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

MILESTONES: List[Tuple[str, str]] = [
    ("committee_referral_date", "소관위원회 회부"),
    ("committee_present_date", "소관위원회 상정"),
    ("committee_process_date", "소관위원회 처리"),
    ("committee_process_result", "소관위원회 처리결과"),
    ("law_submit_date", "법제사법위원회 회부"),
    ("law_present_date", "법제사법위원회 상정"),
    ("law_process_date", "법제사법위원회 처리"),
    ("law_process_result", "법제사법위원회 처리결과"),
    ("plenary_date", "본회의 처리"),
    ("plenary_result", "본회의 처리결과"),
]


def clean(value) -> str:
    return str(value or "").strip()


def first_value(*values) -> str:
    for value in values:
        text = clean(value)
        if text:
            return text
    return ""


def safe_rows(session: requests.Session, endpoint: str, params: Dict[str, str]) -> List[Dict]:
    try:
        data = monitor.request_api(session, endpoint, params)
        return monitor.parse_rows(data, endpoint)
    except RuntimeError as exc:
        if "INFO-200" in str(exc):
            return []
        raise


def fetch_one(session: requests.Session, endpoint: str, bill_id: str, include_age: bool = False) -> Optional[Dict]:
    params = {"pIndex": "1", "pSize": "5", "BILL_ID": bill_id}
    if include_age:
        params["AGE"] = monitor.AGE
    rows = safe_rows(session, endpoint, params)
    return rows[0] if rows else None


def fetch_lifecycle(session: requests.Session, bill_id: str) -> Dict[str, str]:
    member = fetch_one(session, monitor.MEMBER_BILLS_API, bill_id, include_age=True) or {}
    judge = fetch_one(session, JUDGE_API, bill_id) or {}
    processed = fetch_one(session, PROCESSED_API, bill_id, include_age=True) or {}

    if not member and not judge and not processed:
        return {}

    return {
        "committee": first_value(
            member.get("COMMITTEE"),
            judge.get("JRCMIT_NM"),
            processed.get("CURR_COMMITTEE"),
        ),
        "committee_referral_date": first_value(
            member.get("COMMITTEE_DT"),
            judge.get("BDG_CMMT_DT"),
            processed.get("COMMITTEE_DT"),
        ),
        "committee_present_date": first_value(
            member.get("CMT_PRESENT_DT"),
            judge.get("JRCMIT_PRSNT_DT"),
            processed.get("CMT_PRESENT_DT"),
        ),
        "committee_process_date": first_value(
            member.get("CMT_PROC_DT"),
            judge.get("JRCMIT_PROC_DT"),
            processed.get("CMT_PROC_DT"),
        ),
        "committee_process_result": first_value(
            member.get("CMT_PROC_RESULT_CD"),
            judge.get("JRCMIT_PROC_RSLT"),
            processed.get("CMT_PROC_RESULT_CD"),
        ),
        "law_submit_date": first_value(
            member.get("LAW_SUBMIT_DT"),
            processed.get("LAW_SUBMIT_DT"),
        ),
        "law_present_date": first_value(
            member.get("LAW_PRESENT_DT"),
            processed.get("LAW_PRESENT_DT"),
        ),
        "law_process_date": first_value(
            member.get("LAW_PROC_DT"),
            processed.get("LAW_PROC_DT"),
        ),
        "law_process_result": first_value(
            member.get("LAW_PROC_RESULT_CD"),
            processed.get("LAW_PROC_RESULT_CD"),
        ),
        "plenary_date": first_value(
            member.get("PROC_DT"),
            processed.get("PROC_DT"),
        ),
        "plenary_result": first_value(
            member.get("PROC_RESULT"),
            processed.get("PROC_RESULT_CD"),
        ),
        "detail_link": first_value(
            member.get("DETAIL_LINK"),
            judge.get("LINK_URL"),
            processed.get("LINK_URL"),
        ),
    }


def merge_snapshot(previous: Dict, current: Dict) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    keys = {key for key, _ in MILESTONES} | {"committee", "detail_link"}
    for key in keys:
        merged[key] = first_value(current.get(key), previous.get(key))
    return merged


def detect_changes(previous: Dict, current: Dict) -> List[Dict[str, str]]:
    changes = []
    for key, label in MILESTONES:
        old = clean(previous.get(key))
        new = clean(current.get(key))
        if new and new != old:
            changes.append({"field": key, "label": label, "old": old, "new": new})
    return changes


def highest_stage(snapshot: Dict) -> str:
    order = [
        ("plenary_result", "본회의 처리"),
        ("plenary_date", "본회의 처리"),
        ("law_process_result", "법제사법위원회 처리"),
        ("law_process_date", "법제사법위원회 처리"),
        ("law_present_date", "법제사법위원회 상정"),
        ("law_submit_date", "법제사법위원회 회부"),
        ("committee_process_result", "소관위원회 처리"),
        ("committee_process_date", "소관위원회 처리"),
        ("committee_present_date", "소관위원회 상정"),
        ("committee_referral_date", "소관위원회 회부"),
    ]
    for key, label in order:
        if clean(snapshot.get(key)):
            return label
    return "접수"


def esc(value) -> str:
    return html.escape(str(value or "-"))


def build_subject(alerts: List[Dict]) -> str:
    keywords = []
    for alert in alerts:
        keyword = LAW_SUBJECT_KEYWORDS.get(clean(alert.get("matched_law")))
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    suffix = "".join(f"_{keyword}" for keyword in keywords)
    return f"[국회 법률안] 상태변경 {len(alerts)}건{suffix}"


def build_mail_html(alerts: List[Dict]) -> str:
    today = datetime.now(monitor.KST).strftime("%Y.%m.%d")
    blocks = []
    for index, alert in enumerate(alerts, 1):
        changes_html = "".join(
            f'<div style="margin-top:7px;font-size:14px;line-height:1.7;color:#1f2937;">'
            f'<b>{esc(change.get("label"))}</b> · {esc(change.get("new"))}</div>'
            for change in alert.get("changes", [])
        )
        if alert.get("test_mode"):
            changes_html = (
                f'<div style="margin-top:7px;font-size:14px;line-height:1.7;color:#1f2937;">'
                f'<b>테스트 발송</b> · 현재 단계: {esc(alert.get("stage"))}</div>'
            ) + changes_html

        link = clean(alert.get("detail_link")).replace("http://", "https://", 1)
        link_html = (
            f'<div style="margin-top:12px;"><a href="{esc(link)}" '
            f'style="color:#1a73e8;text-decoration:none;font-weight:600;">국회 의안정보 원문 보기 →</a></div>'
            if link else ""
        )

        blocks.append(
            f"""
            <div style="padding:20px 0;border-bottom:1px solid #e5e7eb;">
              <div style="font-size:13px;color:#6b7280;margin-bottom:6px;">상태변경 법률안 {index}</div>
              <div style="font-size:18px;font-weight:700;line-height:1.45;color:#111827;">{esc(alert.get('bill_name'))}</div>
              <div style="margin-top:12px;font-size:14px;line-height:1.8;color:#374151;">
                <b>관리 법률</b> · {esc(alert.get('matched_law'))}<br>
                <b>의안번호</b> · {esc(alert.get('bill_no'))}<br>
                <b>제안일</b> · {esc(alert.get('proposal_date'))}<br>
                <b>소관위원회</b> · {esc(alert.get('committee') or '확인 전')}<br>
                <b>현재 단계</b> · {esc(alert.get('stage'))}
              </div>
              <div style="margin-top:14px;padding:14px 16px;background:#f8fafc;border-radius:8px;">
                <div style="font-size:13px;font-weight:700;color:#475569;margin-bottom:4px;">이번 변경사항</div>
                {changes_html}
              </div>
              {link_html}
            </div>
            """
        )

    return f"""
    <html>
      <body style="margin:0;background:#f5f7fa;font-family:Arial,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;">
        <div style="max-width:680px;margin:0 auto;padding:20px;">
          <div style="background:#ffffff;border-radius:12px;padding:24px;">
            <div style="font-size:13px;color:#6b7280;">국회 법률안 진행상태 모니터링</div>
            <div style="font-size:23px;font-weight:700;margin-top:5px;color:#111827;">상태변경 {len(alerts)}건</div>
            <div style="font-size:14px;color:#6b7280;margin-top:5px;">{today} · 기존 추적 의안 기준</div>
            {''.join(blocks)}
            <div style="font-size:12px;color:#9ca3af;margin-top:18px;line-height:1.6;">
              소관위원회 회부·상정·처리, 법제사법위원회 진행, 본회의 처리 등 의미 있는 단계가 새로 확인될 때만 발송합니다.
            </div>
          </div>
        </div>
      </body>
    </html>
    """


def send_email(alerts: List[Dict]) -> None:
    gmail_user = monitor.required_env("GMAIL_USER")
    gmail_password = monitor.required_env("GMAIL_APP_PASSWORD")
    mail_to = monitor.required_env("MAIL_TO")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = build_subject(alerts)
    msg["From"] = gmail_user
    msg["To"] = mail_to
    msg.attach(MIMEText(build_mail_html(alerts), "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(gmail_user, gmail_password)
        smtp.sendmail(gmail_user, [mail_to], msg.as_string())


def main() -> int:
    seen = monitor.load_seen()
    if not seen:
        print("[INFO] 추적 중인 의안이 없습니다.")
        return 0

    force_test = os.getenv("FORCE_SEND_STATUS_TEST", "false").lower() == "true"
    session = requests.Session()
    session.headers.update(monitor.HEADERS)
    now = datetime.now(monitor.KST).isoformat(timespec="seconds")
    alerts: List[Dict] = []

    try:
        for bill_id, entry in seen.items():
            current_raw = fetch_lifecycle(session, bill_id)
            if not current_raw:
                print(f"[WARN] 상태조회 실패/데이터 없음: {entry.get('bill_no') or bill_id}")
                continue

            previous = entry.get("lifecycle") if isinstance(entry.get("lifecycle"), dict) else {}
            current = merge_snapshot(previous, current_raw)
            changes = detect_changes(previous, current) if previous else []

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
                        "stage": highest_stage(current),
                        "changes": changes,
                    }
                )
                entry["last_status_changed_at"] = now
                print(f"[INFO] 상태변경 감지: {entry.get('bill_no')} / {highest_stage(current)} / {len(changes)}개")
            elif force_test:
                alerts.append(
                    {
                        **entry,
                        "bill_id": bill_id,
                        "committee": current.get("committee"),
                        "detail_link": current.get("detail_link"),
                        "stage": highest_stage(current),
                        "changes": [],
                        "test_mode": True,
                    }
                )
                print(f"[INFO] 테스트 대상: {entry.get('bill_no')} / 현재 단계 {highest_stage(current)}")

        monitor.save_seen(seen)

        if not alerts:
            print("[INFO] 기존 의안 상태변경 없음: 메일을 발송하지 않습니다.")
            return 0

        send_email(alerts)
        if force_test and all(alert.get("test_mode") for alert in alerts):
            print(f"[INFO] 상태변경 테스트 메일 발송 완료: {len(alerts)}건")
        else:
            print(f"[INFO] 상태변경 메일 발송 완료: {len(alerts)}건")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
