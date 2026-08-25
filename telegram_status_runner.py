import status_alert_runner
import status_monitor
import telegram_notify


_original_send_email = status_monitor.send_email


def send_email_and_telegram(alerts):
    _original_send_email(alerts)
    telegram_notify.send_status_alerts(alerts)


status_monitor.send_email = send_email_and_telegram


if __name__ == "__main__":
    raise SystemExit(status_alert_runner.main())
