import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

import enriched_runner
import law_effective_monitor
import monitor
import post_plenary
import status_monitor
import telegram_notify


BILL_NO = os.getenv("TEST_BILL_NO", "2201000").strip()

# 실제 22대 국회 의원발의 → 공포 완료 의안.
# 이 테스트는 날짜를 만들어내지 않고 운영 코드가 외부 데이터에서 읽은 값을 아래 공지값과 대조한다.
TEST_CASES = {
    "2201000": {
        "law_name": "가맹사업거래의 공정화에 관한 법률",
        "bill_name": "가맹사업거래의 공정화에 관한 법률 일부개정법률안",
        "proposal_date": "2024-06-26",
        "committee_referral_date": "2024-06-27",
        "law_submit_date": "2025-10-14",
        "plenary_date": "2025-12-11",
        "government_transfer_date": "2025-12-19",
        "promulgation_date": "2025-12-30",
        "promulgation_no": "21295",
    },
}


def clean(value) -> str:
    return str(value or "").strip()


def norm_date(value) -> str:
    digits = re.sub(r"\D", "", clean(value))
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def assert_equal(label: str, actual, expected) -> None:
    if clean(actual) != clean(expected):
        raise RuntimeError(f"{label} 불일치: actual={actual!r}, expected={expected!r}")
    print(f"[PASS] {label}: {actual}")


def send_test_status(base, label, field, value, stage):
    alert = {
        **base,
        "stage": stage,
        "changes": [{"field": field, "label": label, "old": "", "new": value}],
        "test_mode": True,
    }

    gmail_user = monitor.required_env("GMAIL_USER")
    gmail_password = monitor.required_env("GMAIL_APP_PASSWORD")
    mail_to = monitor.required_env("MAIL_TO")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[TEST REALDATA] [국회 법률안] {label}_{base['matched_law']}"
    msg["From"] = gmail_user
    msg["To"] = mail_to
    msg.attach(MIMEText(status_monitor.build_mail_html([alert]), "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(gmail_user, gmail_password)
        smtp.sendmail(gmail_user, [mail_to], msg.as_string())

    telegram_notify.send_status_alerts([alert])


def main():
    case = TEST_CASES.get(BILL_NO)
    if not case:
        raise RuntimeError(
            f"실데이터 기준값이 등록되지 않은 의안번호입니다: {BILL_NO}. "
            "기본값 2201000으로 실행하세요."
        )

    session = requests.Session()
    session.headers.update(monitor.HEADERS)

    try:
        # 1) 실제 Open Assembly API에서 의안 신원/발의정보를 읽는다.
        lookup = {
            "bill_no": BILL_NO,
            "bill_name": case["bill_name"],
            "matched_law": case["law_name"],
        }
        member = status_monitor.fetch_matching_row(
            session,
            monitor.MEMBER_BILLS_API,
            lookup,
            include_age=True,
        )
        if not member:
            raise RuntimeError(f"국회 Open API에서 의안 {BILL_NO} 신원 확인 실패")

        bill_id = clean(member.get("BILL_ID"))
        if not bill_id:
            raise RuntimeError(f"국회 Open API BILL_ID 없음: {member}")

        bill = {
            "bill_id": bill_id,
            "bill_no": clean(member.get("BILL_NO")) or BILL_NO,
            "bill_name": clean(member.get("BILL_NAME")) or case["bill_name"],
            "matched_law": case["law_name"],
            "proposer": clean(member.get("PROPOSER") or member.get("RST_PROPOSER") or member.get("PUBL_PROPOSER")),
            "proposal_date": norm_date(member.get("PROPOSE_DT")),
            "committee": clean(member.get("COMMITTEE")),
            "detail_link": clean(member.get("DETAIL_LINK")),
        }

        assert_equal("의안번호", bill["bill_no"], BILL_NO)
        assert_equal("법률안명", bill["bill_name"], case["bill_name"])
        assert_equal("제안일", bill["proposal_date"], case["proposal_date"])
        print(f"[PASS] 국회 Open API 신원 확인: BILL_ID={bill_id} / proposer={bill['proposer']}")

        # 2) 실제 운영 상태조회 함수로 소관위→법사위→본회의를 읽는다.
        lifecycle_raw = status_monitor.fetch_lifecycle(session, bill_id, bill)
        if not lifecycle_raw:
            raise RuntimeError("운영 status_monitor.fetch_lifecycle()가 데이터를 반환하지 않음")

        lifecycle = {**lifecycle_raw}
        for field in ("committee_referral_date", "law_submit_date", "plenary_date"):
            lifecycle[field] = norm_date(lifecycle.get(field))

        assert_equal(
            "소관위원회 회부",
            lifecycle["committee_referral_date"],
            case["committee_referral_date"],
        )
        assert_equal(
            "법제사법위원회 회부",
            lifecycle["law_submit_date"],
            case["law_submit_date"],
        )
        assert_equal("본회의 처리", lifecycle["plenary_date"], case["plenary_date"])
        print(f"[PASS] 운영 lifecycle reader / committee={lifecycle.get('committee') or '-'}")

        # 3) 실제 운영 후속단계 함수로 정부이송·공포를 읽는다.
        post = post_plenary.fetch_post_plenary_status(bill, session=session)
        if not post:
            raise RuntimeError("운영 post_plenary.fetch_post_plenary_status()가 데이터를 반환하지 않음")

        assert_equal(
            "정부이송",
            post.get("government_transfer_date"),
            case["government_transfer_date"],
        )
        assert_equal("공포일", post.get("promulgation_date"), case["promulgation_date"])
        assert_equal("공포번호", post.get("promulgation_no"), case["promulgation_no"])
        print(f"[PASS] 운영 post-plenary reader / source={post.get('post_plenary_source') or '-'}")

        # 4) 신규발의 알림은 실제 과거 원문을 현재 enrichment/메일/Telegram 경로로 보낸다.
        enriched_runner.send_email_enriched([bill])
        telegram_notify.send_new_bills([bill])
        print("[PASS] 신규 발의 알림: 실제 원문 + 이메일 + Telegram")

        # 5) 실제 조회된 단계값으로 상태변경 알림을 순차 발송한다.
        status_base = {
            **bill,
            "committee": lifecycle.get("committee") or bill.get("committee"),
            "detail_link": lifecycle.get("detail_link") or bill.get("detail_link"),
        }
        for label, field, stage in [
            ("소관위원회 회부", "committee_referral_date", "소관위원회 회부"),
            ("법제사법위원회 회부", "law_submit_date", "법제사법위원회 회부"),
            ("본회의 처리", "plenary_date", "본회의 처리"),
            ("정부이송", "government_transfer_date", "정부이송"),
        ]:
            value = post.get(field) if field == "government_transfer_date" else lifecycle.get(field)
            send_test_status(status_base, label, field, value, stage)
            print(f"[PASS] {label} 알림: {value}")

        # 6) 국회 공포정보를 실제 법제처 API와 대조하고 시행일을 가져온다.
        oc = monitor.required_env("LAW_API_OC")
        verified = law_effective_monitor.verify_promulgation(
            session,
            oc,
            case["law_name"],
            {
                "promulgation_date": post["promulgation_date"],
                "promulgation_no": post["promulgation_no"],
            },
        )
        if not verified:
            raise RuntimeError(
                f"법제처 공포 교차검증 실패: {post['promulgation_date']} / 제{post['promulgation_no']}호"
            )
        if not verified.get("enforcement_date"):
            raise RuntimeError(f"법제처 시행일 없음: {verified}")

        print(
            "[PASS] 법제처 교차검증:",
            verified.get("promulgation_date"),
            verified.get("promulgation_no"),
            verified.get("enforcement_date"),
        )

        law_effective_monitor.send_promulgation(verified, test_mode=True)
        law_effective_monitor.send_enforcement(
            verified,
            test_mode=True,
            today=verified["enforcement_date"],
        )
        print("[PASS] 공포/시행 알림: 법제처 실데이터 + 이메일 + Telegram")
        print("[SUCCESS] 22대 국회 의원발의 완료 의안 실데이터 전체 체인 테스트 완료")

    finally:
        session.close()


if __name__ == "__main__":
    main()
