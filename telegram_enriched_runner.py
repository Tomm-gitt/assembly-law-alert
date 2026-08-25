import sys

import enriched_runner
import monitor
import telegram_notify


_original_send_email = enriched_runner.send_email_enriched


def send_email_and_telegram(bills):
    _original_send_email(bills)
    telegram_notify.send_new_bills(bills)


monitor.send_email = send_email_and_telegram


if __name__ == "__main__":
    try:
        sys.exit(monitor.main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
