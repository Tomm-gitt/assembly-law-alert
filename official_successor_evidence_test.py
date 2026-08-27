import io
import os
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

import alternative_successor
import monitor


ORIGINAL_BILL_NO = os.getenv("TEST_ORIGINAL_BILL_NO", "2210213").strip()
EXPECTED_SUCCESSOR_NO = os.getenv("TEST_EXPECTED_SUCCESSOR_NO", "2216767").strip()
LAW_NAME = os.getenv("TEST_LAW_NAME", "소비자기본법").strip()
DETAIL_BASE = "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out"


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_digits(value):
    return re.sub(r"\D", "", str(value or ""))


def fetch_html(session, url):
    response = session.get(url, timeout=30)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    return response.text


def extract_plain_text(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return "\n".join(line.strip() for line in soup.get_text("\n", strip=True).splitlines() if line.strip())


def find_pdf_url(detail_url, html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    candidates = []
    for anchor in soup.find_all("a", href=True):
        text = clean(anchor.get_text(" ", strip=True))
        href = clean(anchor.get("href"))
        combined = f"{text} {href}".lower()
        if "pdf" in combined and ("의안원문" in text or "pdf" in href.lower()):
            candidates.append(urljoin(detail_url, href))
    return candidates[0] if candidates else ""


def pdf_text(session, url):
    response = session.get(url, timeout=45)
    response.raise_for_status()
    content = response.content
    if not content.startswith(b"%PDF"):
        raise RuntimeError(f"PDF 응답이 아닙니다: {url} / content-type={response.headers.get('content-type')}")
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


def main():
    session = requests.Session()
    session.headers.update(monitor.HEADERS)
    try:
        original_url = f"{DETAIL_BASE}/{ORIGINAL_BILL_NO}/detailRP"
        original_html = fetch_html(session, original_url)
        original_text = extract_plain_text(original_html)

        if "대안반영폐기" not in re.sub(r"\s+", "", original_text):
            raise RuntimeError("원의안 공식 상세페이지에서 '대안반영폐기'를 확인하지 못했습니다.")
        if monitor.match_watched_law(original_text) != LAW_NAME and LAW_NAME not in original_text:
            raise RuntimeError(f"원의안 법률명 검증 실패: {LAW_NAME}")
        print(f"[PASS] 원의안 대안반영폐기 확인: {ORIGINAL_BILL_NO}")

        original_entry = {
            "bill_no": ORIGINAL_BILL_NO,
            "matched_law": LAW_NAME,
            "proposal_date": "2025-04-29",
        }
        current_lifecycle = {"committee_process_date": "2025-12-17"}
        candidates = alternative_successor.fetch_candidate_alternatives(
            session,
            LAW_NAME,
            monitor.parse_date(current_lifecycle["committee_process_date"]),
        )
        candidates = [c for c in candidates if clean(c.get("bill_no")) != ORIGINAL_BILL_NO]
        if not candidates:
            raise RuntimeError("후속 위원회 대안 후보를 찾지 못했습니다.")
        print("[INFO] 후보 대안:", [(c.get("bill_no"), c.get("bill_name"), c.get("proposal_date")) for c in candidates])

        evidence_matches = []
        for candidate in candidates:
            candidate_no = clean(candidate.get("bill_no"))
            if not candidate_no:
                continue
            detail_url = f"{DETAIL_BASE}/{candidate_no}/detailRP"
            try:
                detail_html = fetch_html(session, detail_url)
                detail_text = extract_plain_text(detail_html)
                if LAW_NAME not in detail_text or "대안" not in detail_text:
                    continue
                pdf_url = find_pdf_url(detail_url, detail_html)
                if not pdf_url:
                    print(f"[WARN] 공식 의안원문 PDF 링크 없음: {candidate_no}")
                    continue
                text = pdf_text(session, pdf_url)
                compact = normalize_digits(text)
                if ORIGINAL_BILL_NO not in compact:
                    print(f"[INFO] PDF에 원의안번호 없음: {candidate_no}")
                    continue
                evidence_matches.append((candidate, pdf_url, text))
                print(f"[PASS] 공식 PDF에서 원의안번호 확인: {ORIGINAL_BILL_NO} -> 후보 {candidate_no}")
            except Exception as exc:
                print(f"[WARN] 후보 공식 PDF 검증 실패: {candidate_no} / {exc}")

        if len(evidence_matches) != 1:
            raise RuntimeError(
                f"공식 PDF 근거가 유일하지 않습니다. 확인 후보 수={len(evidence_matches)} / "
                f"후보={[clean(c.get('bill_no')) for c in candidates]}"
            )

        successor, pdf_url, _ = evidence_matches[0]
        successor_no = clean(successor.get("bill_no"))
        row = exact_receipt_row(session, successor_no)
        if not row:
            raise RuntimeError(f"국회 API에서 대안 의안번호 재검증 실패: {successor_no}")

        api_name = clean(row.get("BILL_NM"))
        api_proposer_kind = clean(row.get("PPSR_KIND"))
        if monitor.match_watched_law(api_name) != LAW_NAME:
            raise RuntimeError(f"대안 법률명 불일치: {api_name}")
        if "대안" not in api_name and "위원" not in api_proposer_kind:
            raise RuntimeError(f"위원회 대안 검증 실패: {api_name} / {api_proposer_kind}")

        if EXPECTED_SUCCESSOR_NO and successor_no != EXPECTED_SUCCESSOR_NO:
            raise RuntimeError(
                f"회귀검증 실패: 기대 대안 {EXPECTED_SUCCESSOR_NO}, 공식근거 탐지 {successor_no}"
            )

        print(f"[PASS] 국회 API 재검증: {successor_no} / {api_name} / {api_proposer_kind}")
        print(f"[PASS] 공식 근거 PDF: {pdf_url}")
        print(f"[SUCCESS] 자동승계 허용 가능한 공식 근거 확인: {ORIGINAL_BILL_NO} -> {successor_no}")
        print("[INFO] DRY-RUN: seen_bills.json은 수정하지 않았습니다.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
