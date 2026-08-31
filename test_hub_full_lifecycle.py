import json
import os
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
        raise RuntimeError("새 테스트 케이스가 INSERTED 되지 않았습니다. 다른 case_id로 다시 실행하세요.")
    print(f"[PASS] 발의 등록 완료: {source_id}")
    print("[NEXT] Telegram에서 자사관련 O로 판정하고 사유 입력 후 phase=continue 실행")


def continue_lifecycle(case_id):
    source_id = f"HUBTEST_{case_id}_ORIGINAL"
    bill_no = f"TEST-{case_id}"
    title = "[허브통합테스트] 소비자기본법 일부개정법률안"

    stages = [
        "소관위원회 회부",
        "법제사법위원회 회부",
        "본회의 처리",
        "정부이송",
        "대안반영폐기",
    ]

    for stage in stages:
        result = post(base_payload(source_id, "법률안 진행상태", title, stage, bill_no))
        action = clean(result.get("action"))
        print(f"[{stage}]", json.dumps(result, ensure_ascii=False))
        if action == "ASSEMBLY_TRACKING_STOPPED":
            raise RuntimeError("원안이 추적중단 상태입니다. register 단계에서 O 판정 여부를 확인하세요.")
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
    print("[CHECK] 후속 대안은 새 sourceId이므로 MASTER/ASSEMBLY_EVENTS와 Telegram 판정 승계 여부를 확인하세요.")


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
