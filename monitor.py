import json
import os
import re
import smtplib
import sys
import time
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import requests

BASE_URL = "https://open.assembly.go.kr/portal/openapi"
MEMBER_BILLS_API = "nzmimeepazxkubdpn"  # 국회의원 발의법률안
RECEIPT_API = "BILLRCP"                 # 의안 접수목록(정부제출/위원회안 포함)
AGE = "22"
ERACO = "제22대"
PAGE_SIZE = 1000
LOOKBACK_DAYS = 7
MAX_PAGES = 10
STATE_PATH = Path("seen_bills.json")

WATCH_LAWS = [
    "식품위생법",
    "건강기능식품에 관한 법률",
    "식품 등의 표시·광고에 관한 법률",
    "제조물 책임법",
    "자원의 절약과 재활용촉진에 관한 법률",
    "농수산물의 원산지 표시 등에 관한 법률",
    "독점규제 및 공정거래에 관한 법률",
    "가맹사업거래의 공정화에 관한 법률",
    "약관의 규제에 관한 법률",
    "소비자기본법",
    "하도급거래 공정화에 관한 법률",
    "전자상거래 등에서의 소비자보호에 관한 법률",
    "표시·광고의 공정화에 관한 법률",
    "인삼산업법",
    "농수산물 품질관리법",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (assembly-law-alert/1.0)",
    "Accept": "application/json,text/plain,*/*",
}


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"필수 환경변수/Secret이 없습니다: {name}")
    return value


def normalize_law_name(text: str) -> str:
    text = str(text or "")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[ㆍ･•]", "·", text)
    return text.strip()


def match_watched_law(bill_name: str) -> Optional[str]:
    normalized_bill = normalize_law_name(bill_name)
    for law in WATCH_LAWS:
        normalized_law = normalize_law_name(law)
        if normalized_bill.startswith(normalized_law):
            return law
    return None


def parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) < 8:
        return None
    try:
        return datetime.strptime(digits[:8], "%Y%m%d").date()
    except ValueError:
        return None


def request_api(session: requests.Session, endpoint: str, params: Dict[str, str]) -> Dict:
    api_key = required_env("ASSEMBLY_API_KEY")
    query = {
        "KEY": api_key,
        "Type": "json",
        **params,
    }
    url = f"{BASE_URL}/{endpoint}"

    last_error = None
    for attempt in range(1, 4):
        try:
            response = session.get(url, params=query, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt * 2)

    raise RuntimeError(f"국회 API 호출 실패: {endpoint}: {last_error}")


def parse_rows(data: Dict, endpoint: str) -> List[Dict]:
    container = data.get(endpoint)
    if container is None:
        for key, value in data.items():
            if key.upper() == endpoint.upper():
                container = value
                break

    if not isinstance(container, list):
        result = data.get("RESULT")
        if isinstance(result, dict):
            raise RuntimeError(
                f"국회 API 오류 {result.get('CODE')}: {result.get('MESSAGE')}"
            )
        raise RuntimeError(f"예상하지 못한 API 응답: {endpoint}: {str(data)[:1000]}")

    rows: List[Dict] = []
    for section in container:
        if not isinstance(section, dict):
            continue

        for head in section.get("head", []) or []:
            if isinstance(head, dict) and isinstance(head.get("RESULT"), dict):
                result = head["RESULT"]
                code = result.get("CODE")
                if code not in ("INFO-000", "INFO-200"):
                    raise RuntimeError(
                        f"국회 API 오류 {code}: {result.get('MESSAGE')}"
                    )

        section_rows = section.get("row")
        if isinstance(section_rows, list):
            rows.extend(section_rows)

    return rows


def fetch_recent_member_bills(session: requests.Session, cutoff: date) -> List[Dict]:
    results: List[Dict] = []

    for page in range(1, MAX_PAGES + 1):
        data = request_api(
            session,
            MEMBER_BILLS_API,
            {
                "pIndex": str(page),
                "pSize": str(PAGE_SIZE),
                "AGE": AGE,
            },
        )
        rows = parse_rows(data, MEMBER_BILLS_API)
        if not rows:
            break

        page_dates = []
        for row in rows:
            proposal_date = parse_date(row.get("PROPOSE_DT"))
            if proposal_date:
                page_dates.append(proposal_date)
            if proposal_date and proposal_date >= cutoff:
                results.append(
                    {
                        "bill_id": row.get("BILL_ID"),
                        "bill_no": row.get("BILL_NO"),
                        "bill_name": row.get("BILL_NAME"),
                        "proposal_date": row.get("PROPOSE_DT"),
                        "proposer": row.get("PROPOSER") or row.get("RST_PROPOSER"),
                        "proposer_kind": "의원발의",
                        "committee": row.get("COMMITTEE"),
                        "process_result": row.get("PROC_RESULT"),
                        "detail_link": row.get("DETAIL_LINK"),
                        "source": MEMBER_BILLS_API,
                    }
                )

        if page_dates and max(page_dates) < cutoff:
            break
        if len(rows) < PAGE_SIZE:
            break

    return results


def fetch_recent_receipts(session: requests.Session, cutoff: date) -> List[Dict]:
    results: List[Dict] = []

    for page in range(1, MAX_PAGES + 1):
        # BILLRCP는 AGE 필터를 신뢰하지 않고 응답의 ERACO로 제22대를 재검증한다.
        data = request_api(
            session,
            RECEIPT_API,
            {
                "pIndex": str(page),
                "pSize": str(PAGE_SIZE),
            },
        )
        rows = parse_rows(data, RECEIPT_API)
        if not rows:
            break

        page_dates = []
        for row in rows:
            if str(row.get("ERACO") or "").strip() != ERACO:
                continue
            if "법률안" not in str(row.get("BILL_KIND") or ""):
                continue

            proposal_date = parse_date(row.get("PPSL_DT"))
            if proposal_date:
                page_dates.append(proposal_date)
            if proposal_date and proposal_date >= cutoff:
                results.append(
                    {
                        "bill_id": row.get("BILL_ID"),
                        "bill_no": row.get("BILL_NO"),
                        "bill_name": row.get("BILL_NM"),
                        "proposal_date": row.get("PPSL_DT"),
                        "proposer": None,
                        "proposer_kind": row.get("PPSR_KIND") or "제안자 정보 없음",
                        "committee": None,
                        "process_result": row.get("PROC_RSLT"),
                        "detail_link": row.get("LINK_URL"),
                        "source": RECEIPT_API,
                    }
                )

        # 최신순 응답을 전제로, 해당 페이지가 전부 컷오프보다 오래되면 중단.
        if page_dates and max(page_dates) < cutoff:
            break
        if len(rows) < PAGE_SIZE:
            break

    return results


def merge_by_bill_id(*groups: Iterable[Dict]) -> List[Dict]:
    merged: Dict[str, Dict] = {}
    for group in groups:
        for bill in group:
            bill_id = str(bill.get("bill_id") or "").strip()
            if not bill_id:
                continue
            if bill_id not in merged:
                merged[bill_id] = dict(bill)
                continue

            current = merged[bill_id]
            for key, value in bill.items():
                if not current.get(key) and value:
                    current[key] = value
            if bill.get("source") == MEMBER_BILLS_API:
                for key in ("proposer", "committee", "detail_link"):
                    if bill.get(key):
                        current[key] = bill[key]
                current["proposer_kind"] = "의원발의"

    return list(merged.values())


def load_seen() -> Dict[str, Dict]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_seen(seen: Dict[str, Dict]) -> None:
    STATE_PATH.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def html_escape(value: Optional[str]) -> str:
    text = str(value or "-")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_mail_html(bills: List[Dict]) -> str:
    today_kst = datetime.utcnow() + timedelta(hours=9)
    blocks = []

    for index, bill in enumerate(bills, 1):
        proposer = bill.get("proposer") or bill.get("proposer_kind") or "-"
        committee = bill.get("committee") or "미정/확인 전"
        result = bill.get("process_result") or "접수"
        link = bill.get("detail_link") or ""

        link_html = ""
        if link:
            link = str(link).replace("http://", "https://", 1)
            link_html = (
                f'<div style="margin-top:10px;">'
                f'<a href="{html_escape(link)}" style="color:#1a73e8;text-decoration:none;">국회 의안정보 보기 →</a>'
                f'</div>'
            )

        blocks.append(
            f"""
            <div style="padding:18px 0;border-bottom:1px solid #e5e7eb;">
              <div style="font-size:13px;color:#6b7280;margin-bottom:6px;">신규 법률안 {index}</div>
              <div style="font-size:18px;font-weight:700;line-height:1.45;color:#111827;">
                {html_escape(bill.get('bill_name'))}
              </div>
              <div style="margin-top:12px;font-size:14px;line-height:1.8;color:#374151;">
                <b>관리 법률</b> · {html_escape(bill.get('matched_law'))}<br>
                <b>의안번호</b> · {html_escape(bill.get('bill_no'))}<br>
                <b>제안일</b> · {html_escape(bill.get('proposal_date'))}<br>
                <b>제안자</b> · {html_escape(proposer)}<br>
                <b>소관위원회</b> · {html_escape(committee)}<br>
                <b>현재 상태</b> · {html_escape(result)}
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
            <div style="font-size:13px;color:#6b7280;">국회 법률안 자동 모니터링</div>
            <div style="font-size:23px;font-weight:700;margin-top:5px;color:#111827;">
              신규 법률안 {len(bills)}건
            </div>
            <div style="font-size:14px;color:#6b7280;margin-top:5px;">
              {today_kst.strftime('%Y.%m.%d')} · 지정 15개 법률 기준
            </div>
            {''.join(blocks)}
            <div style="font-size:12px;color:#9ca3af;margin-top:18px;line-height:1.6;">
              신규 의안 여부를 빠르게 확인하기 위한 자동 알림입니다. 자사 관련 여부는 담당자가 의안 내용을 확인해 판단합니다.
            </div>
          </div>
        </div>
      </body>
    </html>
    """


def send_email(bills: List[Dict]) -> None:
    gmail_user = required_env("GMAIL_USER")
    gmail_password = required_env("GMAIL_APP_PASSWORD")
    mail_to = required_env("MAIL_TO")

    subject = f"[국회 법률안 모니터링] 신규 {len(bills)}건"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = mail_to
    msg.attach(MIMEText(build_mail_html(bills), "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(gmail_user, gmail_password)
        smtp.sendmail(gmail_user, [mail_to], msg.as_string())


def main() -> int:
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS - 1)
    force_send_recent = os.getenv("FORCE_SEND_RECENT", "false").lower() == "true"

    session = requests.Session()
    session.headers.update(HEADERS)

    print(f"[INFO] 기준일: {date.today()} / 조회 시작일: {cutoff}")
    member_bills = fetch_recent_member_bills(session, cutoff)
    print(f"[INFO] 최근 의원발의 법률안: {len(member_bills)}건")

    receipt_bills = fetch_recent_receipts(session, cutoff)
    print(f"[INFO] 최근 접수 법률안: {len(receipt_bills)}건")

    all_bills = merge_by_bill_id(receipt_bills, member_bills)

    watched: List[Dict] = []
    for bill in all_bills:
        matched_law = match_watched_law(str(bill.get("bill_name") or ""))
        if matched_law:
            bill["matched_law"] = matched_law
            watched.append(bill)

    watched.sort(key=lambda x: (str(x.get("proposal_date") or ""), str(x.get("bill_no") or "")), reverse=True)
    print(f"[INFO] 지정 15개 법률 매칭: {len(watched)}건")

    seen = load_seen()
    state_was_empty = not bool(seen)

    if force_send_recent:
        new_bills = watched
        print("[INFO] FORCE_SEND_RECENT=true: 최근 매칭 건을 테스트 메일 대상으로 사용합니다.")
    else:
        new_bills = [bill for bill in watched if bill["bill_id"] not in seen]

    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    for bill in watched:
        bill_id = bill["bill_id"]
        if bill_id not in seen:
            seen[bill_id] = {
                "bill_no": bill.get("bill_no"),
                "bill_name": bill.get("bill_name"),
                "proposal_date": bill.get("proposal_date"),
                "matched_law": bill.get("matched_law"),
                "first_seen_at": now,
            }

    save_seen(seen)

    # 첫 자동 실행에서는 과거 최근 7일분이 한꺼번에 발송되지 않도록 상태만 초기화한다.
    if state_was_empty and not force_send_recent:
        print(f"[INFO] 최초 실행: {len(watched)}건을 기준 데이터로 저장하고 메일은 발송하지 않습니다.")
        return 0

    if not new_bills:
        print("[INFO] 신규 법률안 없음: 메일을 발송하지 않습니다.")
        return 0

    send_email(new_bills)
    print(f"[INFO] 메일 발송 완료: 신규 {len(new_bills)}건")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
