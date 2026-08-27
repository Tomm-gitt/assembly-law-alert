import re

import official_document_evidence as evidence
import official_successor_evidence_test as test
import monitor
import status_monitor


_REFERER_BY_URL = {}
_ORIGINAL_PROPOSER_NAME = ""
_ORIGINAL_FETCH = test.fetch_original_identity_and_lifecycle
_ORIGINAL_COMPACT = test.compact_whitespace


def _extract_proposer_name(value):
    text = test.clean(value)
    match = re.search(r"([가-힣]{2,4})\s*의원", text)
    if match:
        return match.group(1)
    match = re.search(r"([가-힣]{2,4})", text)
    return match.group(1) if match else ""


def fetch_original_identity_and_lifecycle(session):
    global _ORIGINAL_PROPOSER_NAME

    entry, lifecycle, anchor = _ORIGINAL_FETCH(session)
    lookup = {
        "bill_no": test.ORIGINAL_BILL_NO,
        "bill_id": entry.get("bill_id"),
        "bill_name": entry.get("bill_name"),
    }
    try:
        row = status_monitor.fetch_matching_row(
            session,
            monitor.MEMBER_BILLS_API,
            lookup,
            include_age=True,
        ) or {}
        proposer = test.clean(
            row.get("PROPOSER")
            or row.get("RST_PROPOSER")
            or row.get("PUBL_PROPOSER")
        )
        _ORIGINAL_PROPOSER_NAME = _extract_proposer_name(proposer)
        if _ORIGINAL_PROPOSER_NAME:
            print(f"[INFO] 원의안 대표발의자 자동 확인: {_ORIGINAL_PROPOSER_NAME}")
    except Exception as exc:
        print(f"[WARN] 원의안 대표발의자 조회 실패: {exc}")

    return entry, lifecycle, anchor


def compact_whitespace_with_short_bill_no(value):
    """Honor official Assembly documents that omit the Assembly-prefix digits.

    Example: bill 2209981 can be written as '의안번호 9981' in committee
    resolution documents. A shortened number is accepted only when it appears
    in an '의안번호' context and the original representative proposer is also
    present nearby. A bare number is never enough.
    """
    compact = _ORIGINAL_COMPACT(value)
    full_no = test.ORIGINAL_BILL_NO
    if full_no in compact:
        return compact

    age = test.clean(getattr(monitor, "AGE", ""))
    if not age or not full_no.startswith(age):
        return compact

    short_no = full_no[len(age):].lstrip("0")
    if not short_no or not _ORIGINAL_PROPOSER_NAME:
        return compact

    for match in re.finditer(rf"의안번호(?:제)?0*{re.escape(short_no)}(?!\d)", compact):
        start = max(0, match.start() - 120)
        end = min(len(compact), match.end() + 220)
        window = compact[start:end]
        if _ORIGINAL_PROPOSER_NAME in window:
            print(
                f"[PASS] 공식문서 축약 의안번호 확인: "
                f"{full_no} = 의안번호 {short_no} / 대표발의자 {_ORIGINAL_PROPOSER_NAME}"
            )
            return compact + full_no

    return compact


def find_official_document_urls(detail_url, html_text):
    docs = evidence.find_official_document_urls(detail_url, html_text)
    print(f"[INFO] 공식 첨부문서 탐지 수={len(docs)}")
    for label, url in docs:
        _REFERER_BY_URL[url] = detail_url
        print(f"[INFO] 공식 첨부문서 후보: {label} / {url}")
    return docs


def extract_official_document_text(session, url):
    referer = _REFERER_BY_URL.get(url)
    kind, text = evidence.download_and_extract_text(session, url, referer=referer)
    print(
        f"[INFO] 공식 첨부문서 형식 확인: {kind.upper()} / {url} / "
        f"text_len={len(text)} / referer={referer or '-'}"
    )
    return text


def exact_successor_api_row(session, bill_no):
    """Revalidate the discovered successor against multiple official Assembly APIs.

    BILLRCP is unreliable for committee alternatives, so accept only an exact
    BILL_NO match from one of the Assembly endpoints below. The returned row is
    normalized to the field names expected by the existing dry-run test.
    """
    lookup = {"bill_no": bill_no}
    attempts = [
        (monitor.MEMBER_BILLS_API, True),
        (status_monitor.PROCESSED_API, True),
        (monitor.RECEIPT_API, False),
    ]

    for endpoint, include_age in attempts:
        try:
            if endpoint == monitor.RECEIPT_API:
                data = monitor.request_api(
                    session,
                    endpoint,
                    {"pIndex": "1", "pSize": "100", "BILL_NO": bill_no},
                )
                rows = monitor.parse_rows(data, endpoint)
                row = next(
                    (r for r in rows if test.clean(r.get("BILL_NO")) == bill_no),
                    None,
                )
            else:
                row = status_monitor.fetch_matching_row(
                    session,
                    endpoint,
                    lookup,
                    include_age=include_age,
                )
        except Exception as exc:
            print(f"[WARN] 국회 API 재검증 조회 실패: {endpoint} / {bill_no} / {exc}")
            continue

        if not row:
            print(f"[INFO] 국회 API 재검증 미발견: {endpoint} / {bill_no}")
            continue

        row_no = test.clean(row.get("BILL_NO"))
        if row_no != bill_no:
            print(
                f"[WARN] 국회 API 재검증 의안번호 불일치: {endpoint} / "
                f"요청={bill_no} / 응답={row_no or '-'}"
            )
            continue

        bill_name = test.clean(row.get("BILL_NAME") or row.get("BILL_NM"))
        proposer = test.clean(
            row.get("PPSR_KIND")
            or row.get("PROPOSER")
            or row.get("RST_PROPOSER")
            or row.get("PUBL_PROPOSER")
        )
        print(
            f"[INFO] 국회 API 재검증 정확일치: {endpoint} / "
            f"{bill_no} / {bill_name or '-'} / {proposer or '-'}"
        )
        return {
            **row,
            "BILL_NO": row_no,
            "BILL_NM": bill_name,
            "PPSR_KIND": proposer,
            "_verified_endpoint": endpoint,
        }

    return None


# 기존 테스트 본체는 그대로 두고 필요한 I/O/공식문서 표기 훅만 보강한다.
test.fetch_original_identity_and_lifecycle = fetch_original_identity_and_lifecycle
test.compact_whitespace = compact_whitespace_with_short_bill_no
test.find_official_pdf_urls = find_official_document_urls
test.pdf_text = extract_official_document_text
test.exact_receipt_row = exact_successor_api_row


if __name__ == "__main__":
    test.main()
