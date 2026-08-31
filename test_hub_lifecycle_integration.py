import os
from datetime import datetime
from zoneinfo import ZoneInfo

import hub_notify
import monitor

KST = ZoneInfo("Asia/Seoul")

STAGES = [
    "법제사법위원회 회부",
    "본회의 처리",
    "정부이송",
]


def find_bill(bill_no: str):
    seen = monitor.load_seen()
    for bill_id, entry in seen.items():
        if str(entry.get("bill_no") or "").strip() == bill_no:
            return bill_id, dict(entry)
    raise RuntimeError(f"seen_bills.json에서 의안번호 {bill_no}를 찾지 못했습니다.")


def build_payload(bill_id: str, entry: dict, stage: str) -> dict:
    lifecycle = entry.get("lifecycle") or {}
    return {
        "sourceOrg": "국회",
        "sourceType": "법률안 진행상태",
        "sourceId": bill_id,
        "title": str(entry.get("bill_name") or "").strip(),
        "publishedDate": str(entry.get("proposal_date") or "").strip(),
        "originalUrl": str(lifecycle.get("detail_link") or "").replace("http://", "https://", 1),
        "currentStage": stage,
        "stageDate": datetime.now(KST).strftime("%Y-%m-%d"),
        "matchedLaw": str(entry.get("matched_law") or "").strip(),
        "billNo": str(entry.get("bill_no") or "").strip(),
        "committee": str(lifecycle.get("committee") or "").strip(),
    }


def main() -> int:
    bill_no = str(os.getenv("TEST_BILL_NO") or "2220774").strip()
    bill_id, entry = find_bill(bill_no)

    print(f"[INFO] 허브 lifecycle 연동 테스트 시작: {bill_no} / {entry.get('bill_name')}")
    print(f"[INFO] sourceId 유지: {bill_id}")
    print("[INFO] GitHub seen_bills.json은 수정하지 않습니다.")

    for stage in STAGES:
        payload = build_payload(bill_id, entry, stage)
        result = hub_notify._post(payload)
        action = str(result.get("action") or "").strip()
        print(f"[RESULT] {stage}: action={action or result.get('ok')} / response={result}")

        if action == "ASSEMBLY_TRACKING_STOPPED":
            raise RuntimeError(
                f"{bill_no}가 허브에서 추적중단 상태입니다. O 판정 의안으로 테스트해야 합니다."
            )
        if action not in {"ASSEMBLY_STAGE_CHANGED", "UNCHANGED"}:
            raise RuntimeError(f"예상하지 못한 허브 응답: stage={stage}, result={result}")

    print("[PASS] 허브 lifecycle 연동 완료: 법사위 → 본회의 → 정부이송")
    print("[CHECK] MASTER 현재단계=정부이송, 기존 O/사유/판정자/내용 유지 여부 확인")
    print("[CHECK] ASSEMBLY_EVENTS에 단계별 이력 3건 추가 여부 확인")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
