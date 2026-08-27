import io
import re
import struct
import zlib
from urllib.parse import urljoin

import olefile
from bs4 import BeautifulSoup
from pypdf import PdfReader

ATTACHMENT_PATH_RE = re.compile(r"(/better/atchFile/download/\d+)")
OFFICIAL_DOC_KEYWORDS = (
    "의안원문", "위원회의결안", "소관위심사보고서", "심사보고서",
    "법사위문서", "본회의심의안", "본회의회의록", "회의록",
)
OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _label_for_anchor(anchor):
    text = _clean(anchor.get_text(" ", strip=True))
    if text:
        return text
    for attr in ("title", "aria-label", "download"):
        value = _clean(anchor.get(attr))
        if value:
            return value
    parent = anchor.parent
    if parent:
        nearby = _clean(parent.get_text(" ", strip=True))
        for keyword in OFFICIAL_DOC_KEYWORDS:
            if keyword in nearby:
                m = re.search(rf"({re.escape(keyword)}[^\s]*\.(?:hwp|pdf))", nearby, re.I)
                if m:
                    return m.group(1)
        return nearby[:120]
    return "공식 첨부문서"


def find_official_document_urls(detail_url, html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    docs = []
    seen = set()
    for anchor in soup.find_all("a"):
        raw_parts = []
        for attr in ("href", "onclick", "data-url", "data-href", "data-download-url", "data-file-url"):
            value = anchor.get(attr)
            if value:
                raw_parts.append(str(value))
        paths = []
        for raw in raw_parts:
            paths.extend(ATTACHMENT_PATH_RE.findall(raw))
            raw = raw.strip()
            if raw.startswith("/better/atchFile/download/"):
                paths.append(raw)
        if not paths:
            continue
        label = _label_for_anchor(anchor)
        context = _clean(anchor.parent.get_text(" ", strip=True) if anchor.parent else label)
        if not any(keyword in label or keyword in context for keyword in OFFICIAL_DOC_KEYWORDS):
            continue
        for path in paths:
            url = urljoin(detail_url, path)
            if url in seen:
                continue
            seen.add(url)
            docs.append((label, url))
    return docs


def _extract_pdf_text(content):
    reader = PdfReader(io.BytesIO(content))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _strip_hwp_ctrl(data):
    out = bytearray()
    pos = 0
    char_ctrl = {0, 10, 13, *range(24, 32)}
    while pos + 1 < len(data):
        code = int.from_bytes(data[pos:pos + 2], "little")
        if code < 32:
            if code in (10, 13):
                out.extend("\n".encode("utf-16le")); pos += 2
            elif code in char_ctrl:
                pos += 2
            else:
                pos += 16
        else:
            out.extend(data[pos:pos + 2]); pos += 2
    return bytes(out)


def _extract_hwp_text(content):
    with olefile.OleFileIO(io.BytesIO(content)) as ole:
        header = ole.openstream("FileHeader").read()
        if len(header) < 40 or b"HWP Document File" not in header[:32]:
            raise RuntimeError("지원하지 않는 HWP 형식입니다.")
        flags = struct.unpack("<I", header[36:40])[0]
        compressed = bool(flags & 0x01)
        sections = []
        for path in ole.listdir(streams=True, storages=False):
            joined = "/".join(path)
            if joined.startswith("BodyText/Section"):
                sections.append(joined)
        sections.sort(key=lambda x: int(re.search(r"Section(\d+)$", x).group(1)))
        texts = []
        for name in sections:
            data = ole.openstream(name).read()
            if compressed:
                data = zlib.decompress(data, -15)
            pos = 0
            while pos + 4 <= len(data):
                record = int.from_bytes(data[pos:pos + 4], "little"); pos += 4
                tag_id = record & 0x3FF
                size = (record >> 20) & 0xFFF
                if size == 0xFFF:
                    if pos + 4 > len(data): break
                    size = int.from_bytes(data[pos:pos + 4], "little"); pos += 4
                if pos + size > len(data): break
                payload = data[pos:pos + size]; pos += size
                if tag_id != 67 or not payload: continue
                text = _strip_hwp_ctrl(payload).decode("utf-16le", errors="ignore")
                if text.strip(): texts.append(text)
        if texts:
            return "\n".join(texts)
        if ole.exists("PrvText"):
            return ole.openstream("PrvText").read().decode("utf-16le", errors="ignore")
        return ""


def download_and_extract_text(session, url, referer=None):
    headers = {"Referer": referer} if referer else {}
    response = session.get(url, headers=headers, timeout=45, allow_redirects=True)
    response.raise_for_status()
    content = response.content
    if content.startswith(b"%PDF"):
        return "pdf", _extract_pdf_text(content)
    if content.startswith(OLE_MAGIC):
        return "hwp", _extract_hwp_text(content)
    raise RuntimeError(
        f"지원 문서(PDF/HWP)가 아닙니다: {url} / content-type={response.headers.get('content-type')} / size={len(content)}"
    )
