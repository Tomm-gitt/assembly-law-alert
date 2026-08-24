import status_monitor

# 메일 피로도를 줄이기 위해 실제 알림은 핵심 3단계만 사용한다.
# 중간 상정/처리 정보는 국회 API에서 조회될 수 있지만 알림 트리거로는 사용하지 않는다.
status_monitor.MILESTONES = [
    ("committee_referral_date", "소관위원회 회부"),
    ("law_submit_date", "법제사법위원회 회부"),
    ("plenary_date", "본회의 처리"),
]

_original_build_mail_html = status_monitor.build_mail_html


def build_mail_html_filtered(alerts):
    html = _original_build_mail_html(alerts)
    return html.replace(
        "소관위원회 회부·상정·처리, 법제사법위원회 진행, 본회의 처리 등 의미 있는 단계가 새로 확인될 때만 발송합니다.",
        "소관위원회 회부, 법제사법위원회 회부, 본회의 처리의 3개 핵심 단계가 새로 확인될 때만 발송합니다.",
    )


status_monitor.build_mail_html = build_mail_html_filtered


if __name__ == "__main__":
    raise SystemExit(status_monitor.main())
