import hub_notify
import status_alert_runner
import status_monitor
import telegram_notify


_original_send_email = status_monitor.send_email


def send_email_telegram_and_hub(alerts):
    _original_send_email(alerts)

    # 상태변경 알림은 허브의 단계변경 전용 메시지 기능을 붙이기 전까지
    # 기존 Telegram을 유지해 알림 공백이 생기지 않게 한다.
    telegram_notify.send_status_alerts(alerts)

    try:
        hub_notify.send_status_alerts(alerts)
    except Exception as exc:
        # 상태변경 메일/Telegram은 이미 정상 발송되었으므로
        # 허브 동기화 실패만 경고하고 운영 모니터 자체는 실패시키지 않는다.
        print(f"[WARN] 통합 허브 상태변경 동기화 실패: {exc}")


status_monitor.send_email = send_email_telegram_and_hub


if __name__ == "__main__":
    raise SystemExit(status_alert_runner.main())
