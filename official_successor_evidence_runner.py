import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import official_successor_evidence_test as test


ATTACHMENT_PATH_RE = re.compile(r"(/better/atchFile/download/\d+)")
URL_ATTRS = (
    "href",
    "onclick",
    "data-url",
    "data-href",
    "data-download-url",
    "data-file-url",
)


def find_official_pdf_urls(detail_url, html_text):
    """Find official PDF attachments even when the site hides them behind download IDs."""
    soup = BeautifulSoup(html_text, "html.parser")
    urls = []
    seen = set()

    for tag in soup.find_all(True):
        text = test.clean(tag.get_text(" ", strip=True))
        attr_values = []
        for name in URL_ATTRS:
            value = tag.get(name)
            if value:
                attr_values.append(str(value))

        title = test.clean(tag.get("title"))
        aria = test.clean(tag.get("aria-label"))
        combined = " ".join([text, title, aria, *attr_values])
        lowered = combined.lower()

        # Official document label + PDF indication are both required.
        if not any(keyword in combined for keyword in test.OFFICIAL_DOC_KEYWORDS):
            continue
        if "pdf" not in lowered:
            continue

        candidate_urls = []
        for raw in attr_values:
            raw = raw.strip()
            if raw.startswith("http://") or raw.startswith("https://") or raw.startswith("/"):
                candidate_urls.append(urljoin(detail_url, raw))
            for match in ATTACHMENT_PATH_RE.findall(raw):
                candidate_urls.append(urljoin(detail_url, match))

        # Some download IDs are embedded in surrounding HTML/JS rather than href.
        fragment = str(tag)
        for match in ATTACHMENT_PATH_RE.findall(fragment):
            candidate_urls.append(urljoin(detail_url, match))

        for url in candidate_urls:
            if url in seen:
                continue
            seen.add(url)
            urls.append((text or title or aria or "공식 PDF", url))

    # Last-resort scan around raw HTML for attachment download IDs near PDF labels.
    if not urls:
        for match in re.finditer(r".{0,300}pdf.{0,300}", html_text, re.I | re.S):
            chunk = match.group(0)
            if not any(keyword in chunk for keyword in test.OFFICIAL_DOC_KEYWORDS):
                continue
            for path in ATTACHMENT_PATH_RE.findall(chunk):
                url = urljoin(detail_url, path)
                if url not in seen:
                    seen.add(url)
                    urls.append(("공식 PDF", url))

    print(f"[INFO] 공식 PDF 첨부링크 탐지 수={len(urls)}")
    for label, url in urls:
        print(f"[INFO] 공식 PDF 후보 링크: {label} / {url}")
    return urls


test.find_official_pdf_urls = find_official_pdf_urls


if __name__ == "__main__":
    test.main()
