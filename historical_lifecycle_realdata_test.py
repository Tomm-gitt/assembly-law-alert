import html
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

import enriched_runner
import law_effective_monitor
import monitor
import telegram_notify


BILL_NO = os.getenv("TEST_BILL_NO", "2216767").strip()
LAW_NAME = "소비자기본법"
DETAIL_URL = f"https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out/{BILL_NO}/detailRP"


def clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def norm_date(text):
    m = re.search(r"(20\d{2})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})", str(text or ""))
    if not m:
        return ""
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def get_page():
    r = requests.get(DETAIL_URL, headers=monitor.HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding or "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = "\n".join(line.strip() for line in soup.get_text("\n", strip=True).splitlines() if line.strip())
    return text


def extract_between(text, start, stops):
    i = text.find(start)
    if i < 0:
        return ""
    seg = text[i + len(start):]
    ends = [seg.find(s) for s in stops if seg.find(s) > 0]
    return seg[:min(ends)] if ends else seg


def parse_actual(text):
    title_m = re.search(r"(소비자기본법\s+일부개정법률안(?:\(대안\))?)", text)
    proposal_m = re.search(r"발의정보\s+([^\n]+),\s*제" + re.escape(BILL_NO) + r"호\((20\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.)\)", text)
    committee_seg = extract_between(text, "소관위 심사", ["법사위 심사", "본회의 심의"])
    law_seg = extract_between(text, "법사위 심사", ["본회의 심의", "정부이송"])
    plenary_seg = extract_between(text, "본회의 심의", ["정부이송"])
    transfer_seg = extract_between(text, "정부이송", ["목록", "Image:"])

    committee = "정무위원회" if "정무위원회" in committee_seg else ""
    committee_date = norm_date(re.search(r"(?:회부|처리)\s+(20\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.)", committee_seg).group(1)) if re.search(r"(?:회부|처리)\s+(20\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.)", committee_seg) else ""
    law_date = norm_date(re.search(r"회부\s+(20\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.)", law_seg).group(1)) if re.search(r"회부\s+(20\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.)", law_seg) else ""
    plenary_date = norm_date(re.search(r"의결일\s+(20\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.)", plenary_seg).group(1)) if re.search(r"의결일\s+(20\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.)", plenary_seg) else ""
    transfer_date = norm_date(re.search(r"정부이송일\s+(20\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.)", transfer_seg).group(1)) if re.search(r"정부이송일\s+(20\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.)", transfer_seg) else ""
    promulgation_date = norm_date(re.search(r"공포일자\s+(20\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.)", transfer_seg).group(1)) if re.search(r"공포일자\s+(20\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.)", transfer_seg) else ""
    promulgation_no_m = re.search(r"공포번호\s+(\d+)", transfer_seg)

    return {
        "bill_name": clean(title_m.group(1) if title_m else "소비자기본법 일부개정법률안(대안)"),
        "bill_no": BILL_NO,
        "matched_law": LAW_NAME,
        "proposer": clean(proposal_m.group(1) if proposal_m else "정무위원장"),
        "proposal_date": norm_date(proposal_m.group(2)) if proposal_m else "",
        "committee": committee,
        "committee_referral_date": committee_date,
        "law_submit_date": law_date,
        "plenary_date": plenary_date,
        "government_transfer_date": transfer_date,
        "promulgation_date": promulgation_date,
        "promulgation_no": promulgation_no_m.group(1) if promulgation_no_m else "",
        "detail_link": DETAIL_URL,
    }


def send_test_status(base, label, field, value, stage):
    alert = {**base, "stage": stage, "changes": [{"field": field, "label": label, "old": "", "new": value}], "test_mode": True}
    original = __import__("status_monitor")
    gmail_user = monitor.required_env("GMAIL_USER")
    gmail_password = monitor.required_env("GMAIL_APP_PASSWORD")
    mail_to = monitor.required_env("MAIL_TO")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[TEST REALDATA] [국회 법률안] {label}_{LAW_NAME}"
    msg["From"] = gmail_user
    msg["To"] = mail_to
    msg.attach(MIMEText(original.build_mail_html([alert]), "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(gmail_user, gmail_password)
        smtp.sendmail(gmail_user, [mail_to], msg.as_string())
    telegram_notify.send_status_alerts([alert])


def main():
    page = get_page()
    actual = parse_actual(page)
    required = ["proposal_date", "committee_referral_date", "law_submit_date", "plenary_date", "government_transfer_date", "promulgation_date", "promulgation_no"]
    missing = [k for k in required if not actual.get(k)]
    if missing:
        raise RuntimeError(f"실데이터 단계 파싱 실패: {missing} / {actual}")

    print("[PASS] 국회 실데이터 파싱", actual)

    # 1) 신규 발의: 실제 과거 의안 원문으로 현재 신규 알림 렌더러/발송기를 통과시킨다.
    bill = {
        "bill_name": actual["bill_name"],
        "bill_no": actual["bill_no"],
        "matched_law": actual["matched_law"],
        "proposer": actual["proposer"],
        "proposal_date": actual["proposal_date"],
        "committee": actual["committee"],
        "detail_link": actual["detail_link"],
    }
    enriched_runner.send_email_enriched([bill])
    telegram_notify.send_new_bills([bill])
    print("[PASS] 신규 발의 알림")

    # 2~5) 실제 국회 단계값으로 상태변경 알림을 순서대로 발송한다.
    for label, field, stage in [
        ("소관위원회 회부", "committee_referral_date", "소관위원회 회부"),
        ("법제사법위원회 회부", "law_submit_date", "법제사법위원회 회부"),
        ("본회의 처리", "plenary_date", "본회의 처리"),
        ("정부이송", "government_transfer_date", "정부이송"),
    ]:
        send_test_status(actual, label, field, actual[field], stage)
        print(f"[PASS] {label} 알림: {actual[field]}")

    # 6~7) 공포/시행: 국회 공포번호·공포일을 법제처 API와 실제 교차검증한다.
    oc = monitor.required_env("LAW_API_OC")
    session = requests.Session()
    session.headers.update(monitor.HEADERS)
    try:
        verified = law_effective_monitor.verify_promulgation(session, oc, LAW_NAME, {
            "promulgation_date": actual["promulgation_date"],
            "promulgation_no": actual["promulgation_no"],
        })
    finally:
        session.close()
    if not verified:
        raise RuntimeError("법제처 공포 교차검증 실패")
    if not verified.get("enforcement_date"):
        raise RuntimeError(f"법제처 시행일 없음: {verified}")
    print("[PASS] 법제처 교차검증", verified.get("promulgation_date"), verified.get("promulgation_no"), verified.get("enforcement_date"))
    law_effective_monitor.send_promulgation(verified, test_mode=True)
    law_effective_monitor.send_enforcement(verified, test_mode=True, today=verified["enforcement_date"])
    print("[PASS] 공포/시행 알림")
    print("[SUCCESS] 과거 완료 의안 실데이터 전체 체인 테스트 완료")


if __name__ == "__main__":
    main()
