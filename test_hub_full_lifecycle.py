import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

KST = ZoneInfo("Asia/Seoul")
DEFAULT_HUB_WEB_APP_URL = (
    "https://script.google.com/macros/s/"
    "AKfycbzMFcotCh5GjQAQSPok0JAuve75tHQAci3OjUFoj1Xjck3q6vR4JX0uQXwMMeMYrlYVxA/exec"
)


def clean(value):
    return str(value or "").strip()


def hub_url():
    return clean(os.getenv("HUB_WEB_APP_URL")) or DEFAULT_HUB_WEB_APP_URL


def post(payload):
    response = requests.post(hub_url(), json=payload, timeout=30, allow_redirects=True)
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError:
        data = {"ok": True, "raw": response.text}
    if data.get("ok") is False:
        raise RuntimeError(f"허브 처리 실패: {data}")
    return data


def base_payload(source_id, source_type, title, stage, bill_no):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    return {
        "sourceOrg": "국회",
        "sourceType": source_type,
        "sourceId": source_id,
        "title": title,
        "publishedDate": today,
        "originalUrl": "https://likms.assembly.go.kr/bill/billDetail.do?billId=" + source_id,
        "currentStage": stage,
        "stageDate": today,
        "matchedLaw": "소비자기본법",
        "billNo": bill_no,
        "proposer": "허브 통합 테스트",
        "committee": "정무위원회",
    }


def register(case_id):
    source_id = f"HUBTEST_{case_id}_ORIGINAL"
    payload = base_payload(
        source_id,
        "신규 법률안",
        "[허브통합테스트] 소비자기본법 일부개정법률안",
        "발의/접수",
        f"TEST-{case_id}",
    )
    payload["summaryReason"] = "허브 전체 lifecycle 통합 테스트용 원안입니다."
    payload["summaryMainItems"] = [
        "발의부터 단계변경까지 동일 의안의 MASTER 행이 유지되는지 확인",
        "대안반영폐기 후 후속 대안 의안 처리까지 확인",
    ]
    result = post(payload)
    print("[REGISTER]", json.dumps(result, ensure_ascii=False))
    if clean(result.get("action")) != "INSERTED":
        raise RuntimeError(
            "새 테스트 케이스가 INSERTED 되지 않았습니다. 다른 case_id로 다시 실행하세요."
        )
    print(f"[PASS] 발의 등록 완료: {source_id}")
    print("[NEXT] Telegram에서 이 테스트 의안을 자사관련 O로 판정하고 사유를 입력한 뒤 phase=continue를 실행하세요.")


def continue_lifecycle(case_id):
    source_id = f"HUBTEST_{case_id}_ORIGINAL"
    bill_no = f"TEST-{case_id}"
    title = "[허브통합테스트] 소비자기본법 일부개정법률안"

    stages = [
        ("소관위원회 회부", "법률안 진행상태"),
        ("법제사법위원회 회부", "법률안 진행상태"),
        ("본회의 처리", "법률안 진행상태"),
        ("정부이송", "법률안 진행상태"),
        ("대안반영폐기", "법률안 진행상태"),
    ]

    for stage, source_type in stages:
        result = post(base_payload(source_id, source_type, title, stage, bill_no))
        action = clean(result.get("action"))
        print(f"[{stage}]", json.dumps(result, ensure_ascii=False))
        if action == "ASSEMBLY_TRACKING_STOPPED":
            raise RuntimeError(
                "원안이 추적중단 상태입니다. register 단계에서 자사관련 O 판정이 완료됐는지 확인하세요."
            )
        if action not in ("ASSEMBLY_STAGE_CHANGED", "UNCHANGED"):
            raise RuntimeError(f"예상하지 못한 허브 응답: {stage} / {action}")
        time.sleep(1)

    successor_id = f"HUBTEST_{case_id}_ALT"
    successor = base_payload(
        successor_id,
        "대안승계 법률안",
        "[허브통합테스트] 소비자기본법 일부개정법률안(대안)",
        "본회의 처리",
        f"TEST-{case_id}-ALT",
    )
    successor["predecessorSourceId"] = source_id
    successor["summaryReason"] = "원안 대안반영폐기 후 자동 승계되는 후속 대안 테스트입니다."
    successor["summaryMainItems"] = ["원안의 추적 의사결정이 후속 대안으로 이어지는지 확인"]
    result = post(successor)
    print("[대안승계]", json.dumps(result, ensure_ascii=False))

    print("[PASS] 원안 단계 전송 완료: 발의 → 소관위 → 법사위 → 본회의 → 정부이송 → 대안반영폐기")
    print("[CHECK] 후속 대안은 새 sourceId입니다. 허브가 자동 판정승계를 지원하지 않으면 Telegram O/X가 새로 뜰 수 있습니다.")
    print("[CHECK] MASTER/ASSEMBLY_EVENTS와 Telegram을 확인해 대안 승계 동작을 판정하세요.")


def main():
    phase = clean(os.getenv("TEST_PHASE")).lower() or "register"
    case_id = clean(os.getenv("TEST_CASE_ID")) or datetime.now(KST).strftime("%Y%m%d%H%M")
    print(f"[INFO] phase={phase} case_id={case_id}")

    if phase == "register":
        register(case_id)
        return 0
    if phase == "continue":
        continue_lifecycle(case_id)
        return 0
    raise ValueError("TEST_PHASE는 register 또는 continue여야 합니다.")


if __name__ == "__main__":
    raise SystemExit(main())
