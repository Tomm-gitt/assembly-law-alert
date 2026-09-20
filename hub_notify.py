import json
import os
import re
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


def _parse_hub_response(response) -> Dict:
    """Parse direct JSON or the JSON embedded by Apps Script HtmlService."""
    try:
        return response.json()
    except ValueError as direct_json_error:
        body = response.text or ""
        match = re.search(
            r'''["']?userHtml["']?\s*[:=]\s*("(?:\\.|[^"\\])*")''',
            body,
        )
        if match:
            try:
                embedded_text = json.loads(match.group(1))
                return json.loads(embedded_text)
            except (TypeError, ValueError):
                pass

        preview = _clean(body)[:300]
        raise RuntimeError(
            "허브가 JSON이 아닌 응답을 반환했습니다. "
            f"status={response.status_code} body={preview!r}"
        ) from direct_json_error


def _post(payload: Dict) -> Dict:
    """POST to HUB and accept only a real JSON success response.

    Historically a Google Apps Script HTML/error page with HTTP 200 could be
    mistaken for success because non-JSON responses were converted to
    {"ok": True}. That can permanently suppress a NEW_BILL retry after the
    collector records it as seen. Fail closed instead: only JSON {ok:true}
    counts as delivery.
    """
    url = _hub_url()
    last_error = None

    for attempt in range(1, 4):
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=30,
                allow_redirects=True,
            )
            response.raise_for_status()

            data = _parse_hub_response(response)

            if not isinstance(data, dict) or data.get("ok") is not True:
                raise RuntimeError(f"허브 처리 실패: {data}")

            return data
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt * 2)

    raise RuntimeError(f"통합 허브 전송 실패: {last_error}")


def _matched_keywords_from_law(law_name: str) -> List[str]:
    law = _clean(law_name)
    return [law] if law else []


def _fallback_content_from_bill(bill: Dict) -> str:
    reason = _clean(bill.get("proposal_reason_summary"))
    points = [
        _clean(point)
        for point in (bill.get("main_content_points") or [])
        if _clean(point)
    ]

    lines = []
    if reason:
        lines.extend(["■ 제안이유", reason])

    if points:
        if lines:
            lines.append("")
        lines.append("■ 주요내용")
        for index, point in enumerate(points, 1):
            lines.append(f"{index}. {point}")

    return "\n".join(lines).strip()


def _proposer_value(data: Dict) -> str:
    """대표발의자/제안자를 우선하고, 없으면 제안자 구분을 보존한다."""
    return _clean(
        data.get("proposer")
        or data.get("proposer_name")
        or data.get("representative_proposer")
        or data.get("proposer_kind")
    )


def build_new_bill_payload(bill: Dict) -> Dict:
    content = _clean(bill.get("content")) or _fallback_content_from_bill(bill)

    return {
        "eventType": "NEW_BILL",
        "sourceOrg": "국회",
        "sourceType": "신규 법률안",
        "sourceId": _clean(bill.get("hub_source_id") or bill.get("bill_id")),
        "title": _clean(bill.get("bill_name")),
        "publishedDate": _normalize_date(bill.get("proposal_date")),
        "currentStage": _clean(bill.get("process_result")) or "발의/접수",
        "stageDate": _normalize_date(bill.get("proposal_date")),
        "content": content,
        "originalUrl": _clean(bill.get("detail_link")).replace("http://", "https://", 1),
        "matchedKeywords": _matched_keywords_from_law(bill.get("matched_law")),
        "aiUsed": bill.get("ai_used") is True,
        "matchedLaw": _clean(bill.get("matched_law")),
        "billNo": _clean(bill.get("bill_no")),
        "proposer": _proposer_value(bill),
        "proposerKind": _clean(bill.get("proposer_kind")),
        "committee": _clean(bill.get("committee")),
        "summaryReason": _clean(bill.get("proposal_reason_summary")),
        "summaryMainItems": [
            _clean(point)
            for point in (bill.get("main_content_points") or [])
            if _clean(point)
        ],
        "aiModel": _clean(bill.get("ai_model")),
    }


def build_status_payload(alert: Dict) -> Dict:
    payload = {
        "eventType": "STATUS_CHANGE",
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
        "matchedKeywords": _matched_keywords_from_law(alert.get("matched_law")),
        "aiUsed": False,
        "matchedLaw": _clean(alert.get("matched_law")),
        "billNo": _clean(alert.get("bill_no")),
        "proposer": _proposer_value(alert),
        "proposerKind": _clean(alert.get("proposer_kind")),
        "committee": _clean(alert.get("committee")),
        "promulgationDate": _normalize_date(alert.get("promulgation_date")) if _clean(alert.get("promulgation_date")) else "",
        "promulgationNo": _clean(alert.get("promulgation_no")),
        "enforcementDate": _normalize_date(alert.get("enforcement_date")) if _clean(alert.get("enforcement_date")) else "",
    }

    content = _clean(alert.get("content"))
    if content:
        payload["content"] = content

    return payload


def send_new_bills(bills: List[Dict]) -> None:
    if not bills:
        return

    for bill in bills:
        payload = build_new_bill_payload(bill)
        if not _clean(payload.get("content")):
            raise RuntimeError(
                "국회 신규 법률안 content가 비어 있습니다: "
                + (_clean(bill.get("bill_no")) or _clean(bill.get("bill_id")))
            )

        result = _post(payload)
        action = _extract_action(result)
        print(
            "[INFO] 통합 허브 신규 의안 전송 완료: "
            f"{_clean(bill.get('bill_no')) or _clean(bill.get('bill_id'))} / "
            f"ai={payload.get('aiUsed')} / "
            f"{action or result.get('ok')}"
        )


def send_status_alerts(alerts: List[Dict]) -> List[Dict]:
    """국회 lifecycle 이벤트를 HUB로 보내고 추적중단 의안을 제외한다."""
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


def test_build_new_bill_payload() -> Dict:
    bill = {
        "bill_id": "TEST_ASSEMBLY_PAYLOAD_ONLY",
        "bill_no": "9999999",
        "bill_name": "[TEST] 국회 공통 payload 생성 테스트",
        "proposal_date": datetime.now(KST).strftime("%Y-%m-%d"),
        "detail_link": "https://likms.assembly.go.kr/",
        "matched_law": "독점규제 및 공정거래에 관한 법률",
        "proposer": "테스트 의원",
        "committee": "정무위원회",
        "process_result": "",
        "proposal_reason_summary": "공통 payload 생성 여부를 확인하기 위한 테스트입니다.",
        "main_content_points": [
            "content가 Collector에서 완성되어야 합니다.",
            "matchedKeywords와 aiUsed가 포함되어야 합니다.",
        ],
        "ai_used": True,
        "ai_model": "TEST",
    }
    bill["content"] = _fallback_content_from_bill(bill)
    return build_new_bill_payload(bill)


if __name__ == "__main__":
    import json

    print(json.dumps(test_build_new_bill_payload(), ensure_ascii=False, indent=2))
