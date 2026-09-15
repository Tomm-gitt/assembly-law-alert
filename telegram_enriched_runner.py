import sys

import hub_notify
import monitor
from content_enrichment import enrich_bills


def _rollback_seen_for_failed_delivery(bills):
    """Remove just-discovered bills from persisted state so the next run retries them."""
    seen = monitor.load_seen()
    changed = False
    for bill in bills or []:
        bill_id = str(bill.get("bill_id") or "").strip()
        if bill_id and bill_id in seen:
            del seen[bill_id]
            changed = True
    if changed:
        monitor.save_seen(seen)
        print(
            "[WARN] HUB 신규 의안 전달 실패: seen_bills에서 해당 신규 건을 롤백하여 다음 실행에서 재시도합니다."
        )


def enrich_and_send_to_hub(bills):
    """
    신규 법률안 운영 경로.

    원문 수집 -> Gemini AI 요약 -> content 완성 -> HUB 전송.
    HUB의 실제 JSON 성공응답까지 확인되어야 신규 의안 전달 완료로 본다.
    전달 실패 시 monitor.main()이 먼저 기록한 seen 상태를 롤백하여 다음 실행에서 다시 잡는다.
    """
    if not bills:
        return

    enrich_bills(bills)
    try:
        hub_notify.send_new_bills(bills)
    except Exception:
        _rollback_seen_for_failed_delivery(bills)
        raise

    print(f"[INFO] 국회 신규 의안 HUB 전송 전용 처리 완료: {len(bills)}건")


# monitor.main()의 탐지/seen_bills 로직은 유지하되 전송 콜백만 HUB 전용으로 교체한다.
monitor.send_email = enrich_and_send_to_hub


if __name__ == "__main__":
    try:
        sys.exit(monitor.main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise