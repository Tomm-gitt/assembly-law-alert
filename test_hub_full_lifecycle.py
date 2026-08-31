import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import hub_notify
import telegram_notify

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
        "발의부터 단계변경까지 동일 의안의 MASTER 행이 유지되는지 확인",
        "대안반영 후에도 원안 O 판정과 추적상태가 유지되는지 확인",
    ]

    result = hub_notify._post(hub_notify.build_new_bill_payload(bill))
    action = hub_notify._extract_action(result)
    print(f"[REGISTER] action={action}")
    if action != "INSERTED":
        raise RuntimeError(
            f"새 테스트 케이스가 INSERTED 되지 않았습니다(action={action}). 다른 case_id로 다시 실행하세요."
        )

    print(f"[PASS] 발의 등록 완료: {source_id}")
    print("[NEXT] Telegram에서 자사관련 O로 판정하고 사유 입력 후 phase=continue 실행")


def send_operational_status(alert):
    eligible = hub_notify.send_status_alerts([alert])
    if not eligible:
        raise RuntimeError(
            "허브가 상태변경 Telegram 발송을 차단했습니다. register 단계의 O 판정 여부를 확인하세요."
        )
    telegram_notify.send_status_alerts(eligible)


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
        alert = {
            **base,
            "stage": stage,
            "changes": [
                {
                    "field": "hub_full_lifecycle_test",
                    "label": stage,
                    "old": "",
                    "new": datetime.now(KST).strftime("%Y-%m-%d"),
                }
            ],
            "test_mode": True,
        }
        send_operational_status(alert)
        print(f"[PASS] 허브 + 상태변경 Telegram: {stage}")
        time.sleep(1)

    # 실제 운영의 위원회 대안 자동승계와 동일하게 successor의 실제 bill_id는
    # 바뀌지만 hub_source_id는 원안의 허브 identity를 계속 사용한다.
    successor_id = f"HUBTEST_{case_id}_ALT"
    successor_alert = {
        **base_item(
            successor_id,
            "[허브통합테스트] 소비자기본법 일부개정법률안(대안)",
            f"TEST-{case_id}-ALT",
        ),
        "hub_source_id": source_id,
        "stage": "위원회 대안 자동승계",
        "changes": [
            {
                "field": "alternative_successor",
                "label": "대안반영폐기 → 위원회 대안 자동승계",
                "old": bill_no,
                "new": f"TEST-{case_id}-ALT",
            }
        ],
        "test_mode": True,
    }
    send_operational_status(successor_alert)
    print("[PASS] 후속 대안도 원안 hub_source_id로 허브/Telegram 상태변경 처리")
    print("[CHECK] 후속 대안에서 O/X 재판정 메시지가 오면 실패입니다.")
    print("[PASS] 전체 흐름: 발의 → 소관위 → 법사위 → 본회의 → 정부이송 → 대안반영폐기 → 대안 자동승계")


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
