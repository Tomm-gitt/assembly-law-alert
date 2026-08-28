import sys

import enriched_runner
import hub_notify
import monitor
import telegram_notify


_original_send_email = enriched_runner.send_email_enriched


def send_email_and_hub(bills):
    _original_send_email(bills)

    try:
        hub_notify.send_new_bills(bills)
    except Exception as exc:
        # 허브 장애 시 기존 Telegram 알림으로 즉시 fallback.
        # 메일과 신규 의안 감지는 정상 유지한다.
        print(f"[WARN] 통합 허브 전송 실패 - 기존 Telegram fallback: {exc}")
        telegram_notify.send_new_bills(bills)


monitor.send_email = send_email_and_hub


if __name__ == "__main__":
    try:
        sys.exit(monitor.main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
