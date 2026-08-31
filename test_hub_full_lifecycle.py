import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import hub_notify

KST = ZoneInfo("Asia/Seoul")


def clean(value):
    return str(value or "").strip()


def base_item(source_id, title, bill_no):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    return {
        "bill_id": source_id,
        "bill_name": title,
        "bill_no": bill_no,
        "proposal_date": today,
        "detail_link": "https://likms.assembly.go.kr/bill/billDetail.do?billId=" + source_id,
        "matched_law": "소비자기본법",
        "committee": "정무위원회",
        "proposer": "허브 통합 테스트",
    }


def register(case_id):
    source_id = f"HUBTEST_{case_id}_ORIGINAL"
    bill = base_item(
        source_id,
        "[허브통합테스트] 소비자기본법 일부개정법률안",
        f"TEST-{case_id}",
    )
    bill["process_result"] = "발의/접수"
    bill["proposal_reason_summary"] = "허브 전체 lifecycle 통합 테스트용 원안입니다."
    bill["main_content_points"] = [
        "발의부터 시행까지 동일 의안의 MASTER 행이 유지되는지 확인",
        "대안반영 후에도 원안 O 판정과 추적상태가 유지되는지 확인",
        "모든 Telegram 알림이 허브 알림방 하나로만 전송되는지 확인",
    ]

    result = hub_notify._post(hub_notify.build_new_bill_payload(bill))
    action = hub_notify._extract_action(result)
    print(f"[REGISTER] action={action}")
    if action != "INSERTED":
        raise RuntimeError(
            f"새 테스트 케이스가 INSERTED 되지 않았습니다(action={action}). 다른 case_id로 다시 실행하세요."
        )

    print(f"[PASS] 발의 등록 완료: {source_id}")
    print("[NEXT] 허브 Telegram에서 자사관련 O 판정 + 사유 입력 후 phase=continue 실행")


def send_hub_status(alert):
    accepted = hub_notify.send_status_alerts([alert])
    if not accepted:
        raise RuntimeError(
            "허브가 후속 알림을 차단했습니다. register 단계의 O 판정 또는 추적상태를 확인하세요."
        )


def continue_lifecycle(case_id):
    source_id = f"HUBTEST_{case_id}_ORIGINAL"
    bill_no = f"TEST-{case_id}"
    title = "[허브통합테스트] 소비자기본법 일부개정법률안"
    base = base_item(source_id, title, bill_no)

    stages = [
        "소관위원회 회부",
        "법제사법위원회 회부",
        "본회의 처리",
        "정부이송",
        "대안반영폐기",
    ]

    for stage in stages:
        send_hub_status({
            **base,
            "stage": stage,
            "stage_date": datetime.now(KST).strftime("%Y-%m-%d"),
            "test_mode": True,
        })
        print(f"[PASS] 허브 상태변경 처리: {stage}")
        time.sleep(1)

    successor_id = f"HUBTEST_{case_id}_ALT"
    successor_no = f"TEST-{case_id}-ALT"
    successor_base = {
        **base_item(
            successor_id,
            "[허브통합테스트] 소비자기본법 일부개정법률안(대안)",
            successor_no,
        ),
        "hub_source_id": source_id,
    }

    send_hub_status({
        **successor_base,
        "stage": "위원회 대안 자동승계",
        "stage_date": datetime.now(KST).strftime("%Y-%m-%d"),
        "test_mode": True,
    })
    print("[PASS] 위원회 대안 자동승계 - 원안 hub_source_id 유지")
    time.sleep(1)

    today = datetime.now(KST).strftime("%Y-%m-%d")
    send_hub_status({
        **successor_base,
        "stage": "공포",
        "stage_date": today,
        "promulgation_date": today,
        "promulgation_no": "TEST-12345",
        "enforcement_date": today,
        "test_mode": True,
    })
    print("[PASS] 공포 - 허브 처리")
    time.sleep(1)

    send_hub_status({
        **successor_base,
        "stage": "시행",
        "stage_date": today,
        "promulgation_date": today,
        "promulgation_no": "TEST-12345",
        "enforcement_date": today,
        "test_mode": True,
    })
    print("[PASS] 시행 - 허브 처리")

    print("[CHECK] 위 모든 Telegram이 허브 알림방 한 곳에만 와야 합니다.")
    print("[CHECK] 후속 대안에서 O/X 재판정 메시지가 오면 실패입니다.")
    print("[PASS] 전체 흐름: 발의 → 소관위 → 법사위 → 본회의 → 정부이송 → 대안반영폐기 → 대안 자동승계 → 공포 → 시행")


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
