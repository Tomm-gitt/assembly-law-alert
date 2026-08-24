import html
import sys
from typing import Dict, List

import monitor
from content_enrichment import enrich_bills


def esc(value) -> str:
    return html.escape(str(value or "-"))


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


_original_send_email = monitor.send_email


def send_email_enriched(bills: List[Dict]) -> None:
    enrich_bills(bills)
    _original_send_email(bills)


monitor.build_mail_html = build_mail_html_enriched
monitor.send_email = send_email_enriched


if __name__ == "__main__":
    try:
        sys.exit(monitor.main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
