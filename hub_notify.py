import os
import time
from datetime import datetime
from typing import Dict, List
from zoneinfo import ZoneInfo

import requests

KST = ZoneInfo("Asia/Seoul")
DEFAULT_HUB_WEB_APP_URL = (
    "https://script.google.com/macros/s/"
    "AKfycbzMFcotCh5GjQAQSPok0JAuve75tHQAci3OjUFoj1Xjck3q6vR4JX0uQXwMMeMYrlYVxA/exec"
)


def _clean(value) -> str:
    return str(value or "").strip()


def _hub_url() -> str:
    return _clean(os.getenv("HUB_WEB_APP_URL")) or DEFAULT_HUB_WEB_APP_URL


def _normalize_date(value) -> str:
    text = _clean(value)
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return datetime.now(KST).strftime("%Y-%m-%d")


def _extract_action(data: Dict) -> str:
    action = _clean(data.get("action"))
    if action:
        return action
    raw = _clean(data.get("raw"))
    for candidate in (
        "ASSEMBLY_TRACKING_STOPPED",
        "ASSEMBLY_STAGE_CHANGED",
        "UNCHANGED",
        "INSERTED",
    ):
        if candidate in raw:
            return candidate
    return ""


def _post(payload: Dict) -> Dict:
    url = _hub_url()
    last_error = None

    for attempt in range(1, 4):
        try:
            response = requests.post(url, json=payload, timeout=30, allow_redirects=True)
            response.raise_for_status()

            try:
                data = response.json()
            except ValueError:
                data = {"ok": True, "raw": response.text}

            if data.get("ok") is False:
                raise RuntimeError(f"허브 처리 실패: {data}")

            return data
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt * 2)

    raise RuntimeError(f"통합 허브 전송 실패: {last_error}")


def build_new_bill_payload(bill: Dict) -> Dict:
    return {
        "sourceOrg": "국회",
        "sourceType": "신규 법률안",
        "sourceId": _clean(bill.get("hub_source_id") or bill.get("bill_id")),
        "title": _clean(bill.get("bill_name")),
        "publishedDate": _normalize_date(bill.get("proposal_date")),
        "originalUrl": _clean(bill.get("detail_link")).replace("http://", "https://", 1),
        "currentStage": _clean(bill.get("process_result")) or "발의/접수",
        "stageDate": _normalize_date(bill.get("proposal_date")),
        "matchedLaw": _clean(bill.get("matched_law")),
        "billNo": _clean(bill.get("bill_no")),
        "proposer": _clean(bill.get("proposer") or bill.get("proposer_kind")),
        "committee": _clean(bill.get("committee")),
        "summaryReason": _clean(bill.get("proposal_reason_summary")),
        "summaryMainItems": [
            _clean(point)
            for point in (bill.get("main_content_points") or [])
            if _clean(point)
        ],
    }


def build_status_payload(alert: Dict) -> Dict:
    return {
        "sourceOrg": "국회",
        "sourceType": "법률안 진행상태",
        "sourceId": _clean(alert.get("hub_source_id") or alert.get("bill_id")),
        "title": _clean(alert.get("bill_name")),
        "publishedDate": _normalize_date(alert.get("proposal_date")),
        "originalUrl": _clean(alert.get("detail_link")).replace("http://", "https://", 1),
        "currentStage": _clean(alert.get("stage")) or "발의/접수",
        "stageDate": _normalize_date(
            alert.get("stage_date")
            or alert.get("promulgation_date")
            or alert.get("enforcement_date")
        ),
        "matchedLaw": _clean(alert.get("matched_law")),
        "billNo": _clean(alert.get("bill_no")),
        "committee": _clean(alert.get("committee")),
        "promulgationDate": _normalize_date(alert.get("promulgation_date")) if _clean(alert.get("promulgation_date")) else "",
        "promulgationNo": _clean(alert.get("promulgation_no")),
        "enforcementDate": _normalize_date(alert.get("enforcement_date")) if _clean(alert.get("enforcement_date")) else "",
    }


def send_new_bills(bills: List[Dict]) -> None:
    if not bills:
        return

    for bill in bills:
        result = _post(build_new_bill_payload(bill))
        action = _extract_action(result)
        print(
            "[INFO] 통합 허브 신규 의안 전송 완료: "
            f"{_clean(bill.get('bill_no')) or _clean(bill.get('bill_id'))} / "
            f"{action or result.get('ok')}"
        )


def send_status_alerts(alerts: List[Dict]) -> List[Dict]:
    """Send Assembly lifecycle events to the hub.

    The hub is authoritative for tracking and Telegram delivery. If an X
    judgment stopped tracking, the hub returns ASSEMBLY_TRACKING_STOPPED and
    that item is excluded from the returned list. Collectors never send
    Telegram directly.
    """
    if not alerts:
        return []

    accepted: List[Dict] = []

    for alert in alerts:
        result = _post(build_status_payload(alert))
        action = _extract_action(result)
        identity = _clean(alert.get("bill_no")) or _clean(alert.get("bill_id"))

        print(
            "[INFO] 통합 허브 상태변경 전송 완료: "
            f"{identity} / {_clean(alert.get('stage'))} / "
            f"{action or result.get('ok')}"
        )

        if action == "ASSEMBLY_TRACKING_STOPPED":
            print(
                "[INFO] 허브 X 판정(추적중단) 의안 - 후속 알림 제외: "
                f"{identity}"
            )
            continue

        accepted.append(alert)

    return accepted
