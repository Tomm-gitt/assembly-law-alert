import io
import os
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

import alternative_successor
import monitor
import status_monitor


ORIGINAL_BILL_NO = os.getenv("TEST_ORIGINAL_BILL_NO", "2210213").strip()
DETAIL_BASE = "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out"
OFFICIAL_DOC_KEYWORDS = (
    "의안원문",
    "위원회의결안",
    "소관위심사보고서",
    "심사보고서",
    "본회의심의안",
    "본회의회의록",
    "회의록",
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def compact_whitespace(value):
    return re.sub(r"\s+", "", str(value or ""))


def fetch_html(session, url):
    response = session.get(url, timeout=30)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    return response.text


def extract_plain_text(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return "\n".join(
        line.strip()
        for line in soup.get_text("\n", strip=True).splitlines()
        if line.strip()
    )


def find_official_pdf_urls(detail_url, html_text):
    """Return all official-looking PDF links from the bill detail page."""
    soup = BeautifulSoup(html_text, "html.parser")
    urls = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        text = clean(anchor.get_text(" ", strip=True))
        href = clean(anchor.get("href"))
        combined = f"{text} {href}".lower()

        if "pdf" not in combined:
            continue
        if not any(keyword in text for keyword in OFFICIAL_DOC_KEYWORDS) and "pdf" not in href.lower():
            continue

        url = urljoin(detail_url, href)
        if url not in seen:
            seen.add(url)
            urls.append((text or "PDF", url))

    return urls


def pdf_text(session, url):
    response = session.get(url, timeout=45)
    response.raise_for_status()
    content = response.content
    if not content.startswith(b"%PDF"):
        raise RuntimeError(
            f"PDF 응답이 아닙니다: {url} / content-type={response.headers.get('content-type')}"
        )

    reader = PdfReader(io.BytesIO(content))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n".join(pages)


def exact_receipt_row(session, bill_no):
    data = monitor.request_api(
        session,
        monitor.RECEIPT_API,
        {"pIndex": "1", "pSize": "100", "BILL_NO": bill_no},
    )
    rows = monitor.parse_rows(data, monitor.RECEIPT_API)
    for row in rows:
        if clean(row.get("BILL_NO")) == bill_no:
            return row
    return None


def fetch_original_identity_and_lifecycle(session):
    lookup = {"bill_no": ORIGINAL_BILL_NO}
    member = status_monitor.fetch_matching_row(
        session,
        monitor.MEMBER_BILLS_API,
        lookup,
        include_age=True,
    )
    if not member:
        raise RuntimeError(f"국회 API에서 원의안을 찾지 못했습니다: {ORIGINAL_BILL_NO}")

    bill_id = clean(member.get("BILL_ID"))
    bill_name = clean(member.get("BILL_NAME"))
    if not bill_id or not bill_name:
        raise RuntimeError(f"원의안 식별정보가 불완전합니다: {ORIGINAL_BILL_NO}")

    law_name = monitor.match_watched_law(bill_name)
    if not law_name:
        raise RuntimeError(f"관리대상 법률명 자동판별 실패: {bill_name}")

    entry = {
        "bill_id": bill_id,
        "bill_no": ORIGINAL_BILL_NO,
        "bill_name": bill_name,
        "matched_law": law_name,
        "proposal_date": clean(member.get("PROPOSE_DT")),
    }
    lifecycle = status_monitor.fetch_lifecycle(session, bill_id, entry)
    if not lifecycle:
        raise RuntimeError(f"원의안 lifecycle 조회 실패: {ORIGINAL_BILL_NO}")

    result = clean(lifecycle.get("committee_process_result"))
    if not alternative_successor.is_alternative_reflection_result(result):
        raise RuntimeError(
            f"국회 API에서 '대안반영폐기'를 확인하지 못했습니다: {ORIGINAL_BILL_NO} / {result or '-'}"
        )

    process_date = monitor.parse_date(lifecycle.get("committee_process_date"))
    if not process_date:
        raise RuntimeError(
            f"소관위원회 처리일을 자동 확인하지 못했습니다: {ORIGINAL_BILL_NO}"
        )

    return entry, lifecycle, process_date


def main():
    session = requests.Session()
    session.headers.update(monitor.HEADERS)

    try:
        # 1) 테스트가 알고 시작하는 정보는 원의안번호 하나뿐이다.
        entry, lifecycle, anchor = fetch_original_identity_and_lifecycle(session)
        law_name = entry["matched_law"]
        committee = clean(lifecycle.get("committee"))

        print(f"[PASS] 원의안 자동 식별: {ORIGINAL_BILL_NO} / {entry['bill_name']}")
        print(f"[PASS] 관리 법률명 자동 판별: {law_name}")
        print(
            f"[PASS] 대안반영폐기 자동 확인: {ORIGINAL_BILL_NO} / "
            f"{lifecycle.get('committee_process_date')} / {committee or '-'}"
        )

        # 2) 공식 상세페이지에서도 처리결과를 교차확인한다.
        original_url = f"{DETAIL_BASE}/{ORIGINAL_BILL_NO}/detailRP"
        original_html = fetch_html(session, original_url)
        original_text = extract_plain_text(original_html)
        if "대안반영폐기" not in compact_whitespace(original_text):
            raise RuntimeError(
                "원의안 공식 상세페이지에서 '대안반영폐기'를 교차확인하지 못했습니다."
            )
        if law_name not in original_text:
            raise RuntimeError(f"원의안 공식 상세페이지 법률명 검증 실패: {law_name}")
        print("[PASS] 원의안 공식 상세페이지 교차확인")

        # 3) 같은 관리 법률의 위원회 대안을 넓게 후보로만 수집한다.
        # 후보 번호는 사전에 알지 못하며, 이 결과만으로는 절대 PASS하지 않는다.
        candidates = alternative_successor.fetch_candidate_alternatives(
            session,
            law_name,
            anchor,
        )
        candidates = [
            c for c in candidates
            if clean(c.get("bill_no")) and clean(c.get("bill_no")) != ORIGINAL_BILL_NO
        ]
        if not candidates:
            raise RuntimeError("후속 위원회 대안 후보를 찾지 못했습니다.")

        print(
            "[INFO] 자동 수집된 후보 대안:",
            [
                (c.get("bill_no"), c.get("bill_name"), c.get("proposal_date"))
                for c in candidates
            ],
        )

        # 4) 후보별 공식 자료를 모두 열어 원의안번호가 실제로 명시된 후보만 남긴다.
        evidence_matches = []
        for candidate in candidates:
            candidate_no = clean(candidate.get("bill_no"))
            detail_url = f"{DETAIL_BASE}/{candidate_no}/detailRP"

            try:
                detail_html = fetch_html(session, detail_url)
                detail_text = extract_plain_text(detail_html)
                if law_name not in detail_text or "대안" not in detail_text:
                    continue

                official_pdfs = find_official_pdf_urls(detail_url, detail_html)
                if not official_pdfs:
                    print(f"[WARN] 공식 PDF 링크 없음: 후보 {candidate_no}")
                    continue

                matched_docs = []
                for label, pdf_url in official_pdfs:
                    try:
                        text = pdf_text(session, pdf_url)
                    except Exception as exc:
                        print(
                            f"[WARN] 공식 PDF 읽기 실패: 후보 {candidate_no} / "
                            f"{label} / {exc}"
                        )
                        continue

                    if ORIGINAL_BILL_NO not in compact_whitespace(text):
                        continue

                    matched_docs.append((label, pdf_url))
                    print(
                        f"[PASS] 공식문서에서 원의안번호 발견: "
                        f"{ORIGINAL_BILL_NO} -> 후보 {candidate_no} / {label}"
                    )

                if matched_docs:
                    evidence_matches.append((candidate, matched_docs))
                else:
                    print(f"[INFO] 공식문서에 원의안번호 없음: 후보 {candidate_no}")

            except Exception as exc:
                print(f"[WARN] 후보 공식자료 검증 실패: {candidate_no} / {exc}")

        # 5) 공식문서 근거가 정확히 하나의 후보로 수렴해야 한다.
        if len(evidence_matches) != 1:
            raise RuntimeError(
                f"공식근거가 하나의 대안으로 수렴하지 않습니다. "
                f"근거확인 후보 수={len(evidence_matches)} / "
                f"근거후보={[clean(item[0].get('bill_no')) for item in evidence_matches]}"
            )

        successor, matched_docs = evidence_matches[0]
        successor_no = clean(successor.get("bill_no"))

        # 6) 시스템이 스스로 도출한 대안번호를 국회 API로 다시 검증한다.
        row = exact_receipt_row(session, successor_no)
        if not row:
            raise RuntimeError(f"국회 API에서 도출 대안번호 재검증 실패: {successor_no}")

        api_name = clean(row.get("BILL_NM"))
        api_proposer_kind = clean(row.get("PPSR_KIND"))
        if monitor.match_watched_law(api_name) != law_name:
            raise RuntimeError(f"도출 대안의 법률명 불일치: {api_name}")
        if "대안" not in api_name and "위원" not in api_proposer_kind:
            raise RuntimeError(
                f"도출 의안이 위원회 대안으로 검증되지 않음: {api_name} / {api_proposer_kind}"
            )

        print(f"[PASS] 국회 API 재검증: {successor_no} / {api_name} / {api_proposer_kind}")
        for label, url in matched_docs:
            print(f"[PASS] 공식근거: {label} / {url}")

        print(
            f"[SUCCESS] 원의안번호 하나만으로 공식근거 기반 대안 자동도출 성공: "
            f"{ORIGINAL_BILL_NO} -> {successor_no}"
        )
        print("[INFO] DRY-RUN: seen_bills.json은 수정하지 않았습니다.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
