import hub_notify
import status_alert_runner
import status_monitor
import telegram_notify


_original_send_email = status_monitor.send_email


def send_email_telegram_and_hub(alerts):
    _original_send_email(alerts)

    # 국회 상태변경 Telegram은 허브 판정상태를 최종 기준으로 사용한다.
    # X 판정(추적중단) 의안은 허브가 ASSEMBLY_TRACKING_STOPPED를 반환하므로
    # Telegram 발송 대상에서 제외한다.
    try:
        telegram_eligible = hub_notify.send_status_alerts(alerts)
    except Exception as exc:
        # 허브 상태를 확인할 수 없는 경우 X 의안에 잘못 알림을 보내지 않도록
        # fail-closed: 상태변경 Telegram은 보내지 않는다.
        # 이메일은 이미 발송되었고 모니터 자체는 계속 정상 종료한다.
        print(f"[WARN] 통합 허브 판정상태 확인 실패 - 상태변경 Telegram 생략: {exc}")
        return

    if not telegram_eligible:
        print("[INFO] 허브 판정 기준 상태변경 Telegram 발송 대상이 없습니다.")
        return

    telegram_notify.send_status_alerts(telegram_eligible)


status_monitor.send_email = send_email_telegram_and_hub


if __name__ == "__main__":
    raise SystemExit(status_alert_runner.main())
