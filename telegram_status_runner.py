import hub_notify
import status_alert_runner
import status_monitor


def send_status_to_hub(alerts):
    """
    국회 lifecycle 상태변경 운영 경로.

    Collector는 Gmail/Telegram을 직접 보내지 않는다.
    HUB가 tracking 및 Telegram 발송시간 정책을 담당한다.
    """
    try:
        accepted = hub_notify.send_status_alerts(alerts)
    except Exception as exc:
        print(f"[WARN] 통합 허브 상태변경 처리 실패: {exc}")
        raise

    if not accepted:
        print("[INFO] 허브 판정 기준 상태변경 대상이 없습니다.")
        return

    print(f"[INFO] 통합 허브 상태변경 처리 완료: {len(accepted)}건")


# 기존 상태탐지 로직은 그대로 두고 이메일 콜백만 HUB 전송으로 교체한다.
status_monitor.send_email = send_status_to_hub


if __name__ == "__main__":
    raise SystemExit(status_alert_runner.main())
