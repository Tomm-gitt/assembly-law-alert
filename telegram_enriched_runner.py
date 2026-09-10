import sys

import hub_notify
import monitor
from content_enrichment import enrich_bills


def enrich_and_send_to_hub(bills):
    """
    신규 법률안 운영 경로.

    기존:
      원문 수집/정리 -> 국회 Gmail 직접발송 -> HUB

    v2:
      원문 수집 -> Gemini AI 요약 -> content 완성 -> HUB만 전송

    Gmail/Telegram/MASTER/판정/일일보고는 HUB가 담당한다.
    """
    if not bills:
        return

    enrich_bills(bills)
    hub_notify.send_new_bills(bills)

    print(f"[INFO] 국회 신규 의안 HUB 전송 전용 처리 완료: {len(bills)}건")


# monitor.main()의 탐지/seen_bills 로직은 그대로 두고 전송 콜백만 교체한다.
monitor.send_email = enrich_and_send_to_hub


if __name__ == "__main__":
    try:
        sys.exit(monitor.main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
