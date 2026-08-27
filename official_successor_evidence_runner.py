import official_document_evidence as evidence
import official_successor_evidence_test as test
import monitor
import status_monitor


_REFERER_BY_URL = {}


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


# 기존 테스트 본체는 그대로 두고 필요한 I/O 훅만 보강한다.
test.find_official_pdf_urls = find_official_document_urls
test.pdf_text = extract_official_document_text
test.exact_receipt_row = exact_successor_api_row


if __name__ == "__main__":
    test.main()
