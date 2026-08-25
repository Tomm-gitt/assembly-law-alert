import html
import os
from typing import Dict, List

import requests


def _clean(value) -> str:
    return str(value or "").strip()


def _esc(value) -> str:
    return html.escape(_clean(value))


def _telegram_config():
    token = _clean(os.getenv("TELEGRAM_BOT_TOKEN"))
    chat_id = _clean(os.getenv("TELEGRAM_CHAT_ID"))
    if not token or not chat_id:
        print("[WARN] Telegram Secret이 없어 텔레그램 발송을 건너뜁니다.")
        return None, None
    return token, chat_id


def _send(text: str) -> None:
    token, chat_id = _telegram_config()
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API 오류: {data}")


def _trim(text: str, limit: int) -> str:
    text = _clean(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def send_new_bills(bills: List[Dict]) -> None:
    if not bills:
        return

    for bill in bills:
        title = _esc(bill.get("bill_name"))
        law = _esc(bill.get("matched_law"))
        bill_no = _esc(bill.get("bill_no"))
        proposer = _esc(bill.get("proposer") or bill.get("proposer_kind") or "-")
        proposal_date = _esc(bill.get("proposal_date") or "-")
        committee = _esc(bill.get("committee") or "미정/확인 전")
        reason = _trim(bill.get("proposal_reason_summary") or "", 700)
        points = bill.get("main_content_points") or []
        link = _clean(bill.get("detail_link")).replace("http://", "https://", 1)

        lines = [
            "🏛️ <b>[국회 법률안] 신규</b>",
            "",
            f"<b>{title}</b>",
            f"• 관리 법률: {law}",
            f"• 의안번호: {bill_no}",
            f"• 제안자: {proposer}",
            f"• 제안일: {proposal_date}",
            f"• 소관위원회: {committee}",
        ]

        if reason:
            lines.extend(["", "<b>[제안이유]</b>", _esc(reason)])

        if points:
            lines.extend(["", "<b>[주요내용]</b>"])
            for i, point in enumerate(points, 1):
                candidate = f"{i}. {_esc(_trim(point, 550))}"
                if len("\n".join(lines + [candidate])) > 3600:
                    lines.append("… 주요내용이 길어 나머지는 이메일/국회 원문에서 확인")
                    break
                lines.append(candidate)

        if link:
            lines.extend(["", f'<a href="{html.escape(link, quote=True)}">국회 의안정보 원문 보기 →</a>'])

        _send("\n".join(lines))

    print(f"[INFO] Telegram 신규 의안 알림 발송 완료: {len(bills)}건")


def send_status_alerts(alerts: List[Dict]) -> None:
    if not alerts:
        return

    for alert in alerts:
        title = _esc(alert.get("bill_name"))
        bill_no = _esc(alert.get("bill_no"))
        law = _esc(alert.get("matched_law"))
        committee = _esc(alert.get("committee") or "확인 전")
        stage = _esc(alert.get("stage") or "-")
        link = _clean(alert.get("detail_link")).replace("http://", "https://", 1)

        if alert.get("test_mode"):
            change_lines = [f"• 테스트 발송 · 현재 단계: {stage}"]
        else:
            change_lines = [
                f"• {_esc(change.get('label'))}: {_esc(change.get('new'))}"
                for change in alert.get("changes", [])
            ]

        lines = [
            "🔔 <b>[국회 법률안] 상태변경</b>",
            "",
            f"<b>{title}</b>",
            f"• 관리 법률: {law}",
            f"• 의안번호: {bill_no}",
            f"• 소관위원회: {committee}",
            f"• 현재 단계: {stage}",
            "",
            "<b>[이번 변경사항]</b>",
            *change_lines,
        ]

        if link:
            lines.extend(["", f'<a href="{html.escape(link, quote=True)}">국회 의안정보 원문 보기 →</a>'])

        _send("\n".join(lines))

    print(f"[INFO] Telegram 상태변경 알림 발송 완료: {len(alerts)}건")
