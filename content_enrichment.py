import re
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

LIKMS_BASE = "https://likms.assembly.go.kr/bill/billDetail.do"

STOP_MARKERS = [
    "소관위 심사정보",
    "위원회 심사",
    "위원회 심사정보",
    "체계자구심사",
    "법사위 심사정보",
    "본회의 심의",
    "본회의 심의정보",
    "정부이송",
    "공포",
    "부가정보",
    "의안원문",
]


def clean_inline(text: str) -> str:
    text = str(text or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_detail_url(bill: Dict) -> str:
    link = str(bill.get("detail_link") or "").strip()
    if link:
        return link.replace("http://", "https://", 1)
    bill_id = str(bill.get("bill_id") or "").strip()
    if not bill_id:
        return ""
    return f"{LIKMS_BASE}?billId={bill_id}&ageFrom=22&ageTo=22"


def _extract_relevant_segment(page_text: str) -> str:
    candidates = [
        "▶ 제안이유 및 주요내용",
        "제안이유 및 주요내용",
        "대안의 제안이유 및 주요내용",
    ]

    start = -1
    marker = ""
    for candidate in candidates:
        idx = page_text.find(candidate)
        if idx >= 0 and (start < 0 or idx < start):
            start = idx
            marker = candidate

    if start < 0:
        return ""

    segment = page_text[start + len(marker):]
    end_positions = []
    for stop in STOP_MARKERS:
        idx = segment.find(stop)
        if idx > 0:
            end_positions.append(idx)
    if end_positions:
        segment = segment[: min(end_positions)]

    return clean_inline(segment)


def _split_reason_main(segment: str) -> Dict[str, str]:
    if not segment:
        return {"proposal_reason": "", "main_content": ""}

    text = segment
    text = re.sub(r"^(?:제안이유 및 주요내용|대안의 제안이유 및 주요내용)\s*", "", text).strip()

    reason_match = re.search(
        r"(?:^|\n)(?:대안의\s*)?제안이유\s*(.*?)(?=\n(?:대안의\s*)?주요내용\s*(?:\n|$))",
        text,
        flags=re.S,
    )
    main_match = re.search(
        r"(?:^|\n)(?:대안의\s*)?주요내용\s*(.*)$",
        text,
        flags=re.S,
    )

    if reason_match or main_match:
        reason = clean_inline(reason_match.group(1) if reason_match else "")
        main = clean_inline(main_match.group(1) if main_match else "")
        return {"proposal_reason": reason, "main_content": main}

    # 일부 법안은 제안이유와 주요내용을 구분하지 않고 하나의 본문으로 제공한다.
    return {"proposal_reason": "", "main_content": clean_inline(text)}


def fetch_bill_content(bill: Dict, session: Optional[requests.Session] = None) -> Dict[str, str]:
    url = build_detail_url(bill)
    if not url:
        return {
            "proposal_reason": "",
            "main_content": "",
            "content_source": "",
            "content_error": "상세 링크가 없습니다.",
        }

    own_session = session is None
    session = session or requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/151 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
        }
    )

    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding or "utf-8"

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        raw_text = soup.get_text("\n", strip=True)
        raw_text = clean_inline(raw_text)
        segment = _extract_relevant_segment(raw_text)
        parts = _split_reason_main(segment)

        if not parts["proposal_reason"] and not parts["main_content"]:
            return {
                "proposal_reason": "",
                "main_content": "",
                "content_source": "LIKMS",
                "content_error": "제안이유 및 주요내용 영역을 찾지 못했습니다.",
            }

        return {
            **parts,
            "content_source": "LIKMS",
            "content_error": "",
        }
    except Exception as exc:
        return {
            "proposal_reason": "",
            "main_content": "",
            "content_source": "LIKMS",
            "content_error": str(exc),
        }
    finally:
        if own_session:
            session.close()


def summarize_reason(text: str, max_chars: int = 650) -> str:
    text = clean_inline(text)
    if not text:
        return ""

    sentences = [s.strip() for s in re.split(r"(?<=[.!?。]|[임됨함])\s+", text) if s.strip()]
    if not sentences:
        return text[:max_chars]

    out = ""
    for sentence in sentences[:3]:
        candidate = (out + " " + sentence).strip()
        if len(candidate) > max_chars and out:
            break
        out = candidate
    return out or text[:max_chars]


def main_content_points(text: str) -> List[str]:
    text = clean_inline(text)
    if not text:
        return []

    # 원문에서 이미 항목 구분(○, ①, 가., 1. 등)이 있으면 그 구조를 최대한 유지한다.
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    bullet_re = re.compile(r"^(?:[○●□■※▶▷]|\(?\d+\)?[.)]|[①-⑳]|[가-하][.)])\s*")

    if sum(1 for line in raw_lines if bullet_re.match(line)) >= 2:
        points: List[str] = []
        current = ""
        for line in raw_lines:
            if bullet_re.match(line):
                if current:
                    points.append(clean_inline(current))
                current = bullet_re.sub("", line).strip()
            else:
                current = (current + " " + line).strip() if current else line
        if current:
            points.append(clean_inline(current))
        return [p for p in points if p]

    # 구조가 없는 단일 문단은 문장을 350자 안팎의 덩어리로 나눠 원문 누락 없이 번호화한다.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?。])\s+|(?<=임)\s+|(?<=함)\s+", text) if s.strip()]
    if len(sentences) <= 1:
        return [text]

    points = []
    current = ""
    for sentence in sentences:
        candidate = (current + " " + sentence).strip()
        if current and len(candidate) > 350:
            points.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        points.append(current)
    return points


def enrich_bills(bills: List[Dict]) -> None:
    session = requests.Session()
    try:
        for bill in bills:
            content = fetch_bill_content(bill, session=session)
            bill.update(content)
            bill["proposal_reason_summary"] = summarize_reason(content.get("proposal_reason", ""))
            bill["main_content_points"] = main_content_points(content.get("main_content", ""))
            print(
                "[INFO] 원문 수집",
                bill.get("bill_no"),
                f"reason={len(content.get('proposal_reason', ''))}",
                f"main={len(content.get('main_content', ''))}",
                f"error={content.get('content_error') or '-'}",
            )
    finally:
        session.close()
