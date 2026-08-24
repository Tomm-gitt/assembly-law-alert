import html
import sys
from typing import Dict, List

import monitor
from content_enrichment import enrich_bills


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


def esc(value) -> str:
    return html.escape(str(value or "-"))


def build_subject(bills: List[Dict]) -> str:
    keywords = []
    for bill in bills:
        law = str(bill.get("matched_law") or "").strip()
        keyword = LAW_SUBJECT_KEYWORDS.get(law)
        if keyword and keyword not in keywords:
            keywords.append(keyword)

    suffix = "".join(f"_{keyword}" for keyword in keywords)
    return f"[국회 법률안] 신규 {len(bills)}건{suffix}"


def build_mail_html_enriched(bills: List[Dict]) -> str:
    today_kst = monitor.datetime.now(monitor.KST)
    blocks = []

    for index, bill in enumerate(bills, 1):
        proposer = bill.get("proposer") or bill.get("proposer_kind") or "-"
        committee = bill.get("committee") or "미정/확인 전"
        result = bill.get("process_result") or "접수"
        link = str(bill.get("detail_link") or "").replace("http://", "https://", 1)

        reason = bill.get("proposal_reason_summary") or ""
        points = bill.get("main_content_points") or []
        content_error = bill.get("content_error") or ""

        if reason:
            reason_html = f"""
              <div style="margin-top:16px;padding:14px 16px;background:#f8fafc;border-radius:8px;">
                <div style="font-size:13px;font-weight:700;color:#475569;margin-bottom:7px;">제안이유</div>
                <div style="font-size:14px;line-height:1.75;color:#1f2937;">{esc(reason)}</div>
              </div>
            """
        else:
            reason_html = ""

        if points:
            if len(points) == 1:
                point_items = (
                    f'<div style="margin-top:7px;font-size:14px;line-height:1.7;color:#1f2937;">'
                    f'{esc(points[0])}</div>'
                )
            else:
                point_items = "".join(
                    f'<div style="display:flex;gap:8px;margin-top:7px;">'
                    f'<div style="font-weight:700;color:#334155;min-width:18px;">{i}.</div>'
                    f'<div style="font-size:14px;line-height:1.7;color:#1f2937;">{esc(point)}</div>'
                    f'</div>'
                    for i, point in enumerate(points, 1)
                )
            main_html = f"""
              <div style="margin-top:14px;padding:14px 16px;background:#fffaf0;border-radius:8px;">
                <div style="font-size:13px;font-weight:700;color:#92400e;margin-bottom:5px;">주요내용</div>
                {point_items}
              </div>
            """
        elif content_error:
            main_html = f"""
              <div style="margin-top:14px;padding:12px 14px;background:#fff7ed;border-radius:8px;font-size:13px;line-height:1.6;color:#9a3412;">
                제안이유·주요내용 자동수집 실패: {esc(content_error)}<br>
                아래 국회 의안정보 링크에서 원문을 확인해주세요.
              </div>
            """
        else:
            main_html = ""

        link_html = ""
        if link:
            link_html = (
                f'<div style="margin-top:12px;">'
                f'<a href="{esc(link)}" style="color:#1a73e8;text-decoration:none;font-weight:600;">국회 의안정보 원문 보기 →</a>'
                f'</div>'
            )

        blocks.append(
            f"""
            <div style="padding:20px 0;border-bottom:1px solid #e5e7eb;">
              <div style="font-size:13px;color:#6b7280;margin-bottom:6px;">신규 법률안 {index}</div>
              <div style="font-size:18px;font-weight:700;line-height:1.45;color:#111827;">{esc(bill.get('bill_name'))}</div>
              <div style="margin-top:12px;font-size:14px;line-height:1.8;color:#374151;">
                <b>관리 법률</b> · {esc(bill.get('matched_law'))}<br>
                <b>의안번호</b> · {esc(bill.get('bill_no'))}<br>
                <b>제안일</b> · {esc(bill.get('proposal_date'))}<br>
                <b>제안자</b> · {esc(proposer)}<br>
                <b>소관위원회</b> · {esc(committee)}<br>
                <b>현재 상태</b> · {esc(result)}
              </div>
              {reason_html}
              {main_html}
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
            <div style="font-size:23px;font-weight:700;margin-top:5px;color:#111827;">신규 법률안 {len(bills)}건</div>
            <div style="font-size:14px;color:#6b7280;margin-top:5px;">{today_kst.strftime('%Y.%m.%d')} · 지정 15개 법률 기준</div>
            {''.join(blocks)}
            <div style="font-size:12px;color:#9ca3af;margin-top:18px;line-height:1.6;">
              제안이유는 모바일 확인용으로 압축 표시하며, 주요내용은 원문 항목을 가능한 한 빠짐없이 구조화합니다. 중요한 판단은 국회 원문을 함께 확인하세요.
            </div>
          </div>
        </div>
      </body>
    </html>
    """


def send_email_enriched(bills: List[Dict]) -> None:
    enrich_bills(bills)

    gmail_user = monitor.required_env("GMAIL_USER")
    gmail_password = monitor.required_env("GMAIL_APP_PASSWORD")
    mail_to = monitor.required_env("MAIL_TO")

    msg = monitor.MIMEMultipart("alternative")
    msg["Subject"] = build_subject(bills)
    msg["From"] = gmail_user
    msg["To"] = mail_to
    msg.attach(monitor.MIMEText(build_mail_html_enriched(bills), "html", "utf-8"))

    with monitor.smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(gmail_user, gmail_password)
        smtp.sendmail(gmail_user, [mail_to], msg.as_string())


monitor.build_mail_html = build_mail_html_enriched
monitor.send_email = send_email_enriched


if __name__ == "__main__":
    try:
        sys.exit(monitor.main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
