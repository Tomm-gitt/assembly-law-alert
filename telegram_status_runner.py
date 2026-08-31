import hub_notify
import status_alert_runner
import status_monitor


_original_send_email = status_monitor.send_email


def send_email_telegram_and_hub(alerts):
    _original_send_email(alerts)

    # 상태변경 Telegram 발송 책임은 통합 허브로 중앙화한다.
    # 허브는 자신의 TELEGRAM_CHAT_ID를 사용하므로 신규 O/X와 상태변경이
    # 항상 같은 허브 알림방으로 간다. X 판정 의안은 허브에서 추적중단 처리된다.
    try:
        telegram_eligible = hub_notify.send_status_alerts(alerts)
    except Exception as exc:
        # 이메일은 이미 발송되었고, 허브 동기화/Telegram 실패는 로그로 남긴다.
        print(f"[WARN] 통합 허브 상태변경 처리 실패: {exc}")
        return

    if not telegram_eligible:
        print("[INFO] 허브 판정 기준 상태변경 대상이 없습니다.")
        return

    print(f"[INFO] 통합 허브 상태변경 처리 완료: {len(telegram_eligible)}건")


status_monitor.send_email = send_email_telegram_and_hub


if __name__ == "__main__":
    raise SystemExit(status_alert_runner.main())
