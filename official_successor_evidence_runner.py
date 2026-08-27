import official_document_evidence as evidence
import official_successor_evidence_test as test


def find_official_document_urls(detail_url, html_text):
    docs = evidence.find_official_document_urls(detail_url, html_text)
    print(f"[INFO] 공식 첨부문서 탐지 수={len(docs)}")
    for label, url in docs:
        print(f"[INFO] 공식 첨부문서 후보: {label} / {url}")
    return docs


def extract_official_document_text(session, url):
    kind, text = evidence.download_and_extract_text(session, url)
    print(f"[INFO] 공식 첨부문서 형식 확인: {kind.upper()} / {url} / text_len={len(text)}")
    return text


# 기존 테스트 본체는 그대로 두고, 'PDF 전용' 훅을 '공식 PDF/HWP 문서' 훅으로 교체한다.
test.find_official_pdf_urls = find_official_document_urls
test.pdf_text = extract_official_document_text


if __name__ == "__main__":
    test.main()
