import sys

import enriched_runner
import hub_notify
import monitor


_original_send_email = enriched_runner.send_email_enriched


def send_email_and_hub(bills):
    _original_send_email(bills)

    # 신규 의안 Telegram/OX 알림은 통합 허브가 전담한다.
    # 국회 저장소는 허브 장애 시에도 별도 Telegram fallback을 보내지 않는다.
    # 이렇게 해야 모든 기관 알림이 허브의 Bot/Chat ID 하나로 유지된다.
    hub_notify.send_new_bills(bills)


monitor.send_email = send_email_and_hub


if __name__ == "__main__":
    try:
        sys.exit(monitor.main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
