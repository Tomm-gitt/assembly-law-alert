import sys
from typing import Dict, List, Tuple

import requests

import monitor

AGES = ("22", "21", "20")
PAGE_SIZE = 30


def query_variants(law: str) -> List[str]:
    variants = [law]
    if "·" in law:
        variants.append(law.replace("·", "ㆍ"))
    if "ㆍ" in law:
        variants.append(law.replace("ㆍ", "·"))
    return list(dict.fromkeys(variants))


def fetch_samples(session: requests.Session, law: str) -> Tuple[str, List[Dict]]:
    """Find real Assembly member-sponsored bill samples, preferring the 22nd Assembly."""
    for age in AGES:
        collected: Dict[str, Dict] = {}
        for query in query_variants(law):
            data = monitor.request_api(
                session,
                monitor.MEMBER_BILLS_API,
                {
                    "pIndex": "1",
                    "pSize": str(PAGE_SIZE),
                    "AGE": age,
                    "BILL_NAME": query,
                },
            )
            rows = monitor.parse_rows(data, monitor.MEMBER_BILLS_API)
            for row in rows:
                bill_id = str(row.get("BILL_ID") or "")
                if bill_id:
                    collected[bill_id] = row

        exact_matches = []
        for row in collected.values():
            bill_name = str(row.get("BILL_NAME") or "")
            if monitor.match_watched_law(bill_name) == law:
                exact_matches.append(row)

        if exact_matches:
            exact_matches.sort(
                key=lambda x: (str(x.get("PROPOSE_DT") or ""), str(x.get("BILL_NO") or "")),
                reverse=True,
            )
            return age, exact_matches

    return "", []


def run_normalization_checks() -> List[str]:
    failures = []
    suffix = " 일부개정법률안"
    for law in monitor.WATCH_LAWS:
        variants = {
            law,
            law.replace("·", "ㆍ"),
            law.replace("·", "･"),
            law.replace(" ", "  "),
        }
        for variant in variants:
            title = variant + suffix
            result = monitor.match_watched_law(title)
            if result != law:
                failures.append(f"{law} <- {title!r} => {result!r}")
    return failures


def main() -> int:
    session = requests.Session()
    session.headers.update(monitor.HEADERS)

    print("=" * 72)
    print("15개 관리 법률 실제 국회 의안 매칭 검증")
    print("- 제22대 실제 의안을 우선 검색하고, 샘플이 없으면 21·20대까지 확인")
    print("- 운영 seen_bills.json / Gmail에는 전혀 영향을 주지 않음")
    print("=" * 72)

    normalization_failures = run_normalization_checks()
    if normalization_failures:
        print("\n[FAIL] 문장부호/공백 정규화 자체 테스트 실패")
        for item in normalization_failures:
            print("  -", item)
    else:
        print("\n[PASS] 문장부호/공백 정규화 테스트 전체 통과")

    passed = 0
    failed: List[str] = []
    current_assembly = 0

    try:
        for index, law in enumerate(monitor.WATCH_LAWS, 1):
            age, rows = fetch_samples(session, law)
            if not rows:
                failed.append(law)
                print(f"\n[{index:02d}/15] FAIL | {law}")
                print("  실제 의원발의 샘플을 제20~22대에서 찾지 못함")
                continue

            row = rows[0]
            bill_name = str(row.get("BILL_NAME") or "")
            matched = monitor.match_watched_law(bill_name)
            ok = matched == law
            status = "PASS" if ok else "FAIL"
            if ok:
                passed += 1
            else:
                failed.append(law)
            if age == "22":
                current_assembly += 1

            print(f"\n[{index:02d}/15] {status} | {law}")
            print(f"  실제 샘플: 제{age}대 / 의안번호 {row.get('BILL_NO') or '-'}")
            print(f"  법률안명: {bill_name}")
            print(f"  매칭 결과: {matched or '매칭 없음'}")
            print(f"  제안일: {row.get('PROPOSE_DT') or '-'}")

        print("\n" + "=" * 72)
        print(f"검증 결과: {passed}/15 PASS")
        print(f"제22대 실제 샘플로 검증된 법률: {current_assembly}/15")
        if failed:
            print("확인 필요:", ", ".join(failed))
        else:
            print("결론: 15개 법률 모두 실제 국회 의안명에서 정확히 매칭됨")
        print("=" * 72)

        return 1 if failed or normalization_failures else 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
