import re
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

LIKMS_BASE = "https://likms.assembly.go.kr/bill/billDetail.do"
LAWMAKING_BASE = "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out"

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


def build_lawmaking_url(bill: Dict) -> str:
    bill_no = re.sub(r"\D", "", str(bill.get("bill_no") or ""))
    if not bill_no:
        return ""
    return f"{LAWMAKING_BASE}/{bill_no}/detailRP"


def _extract_relevant_segment(page_text: str) -> str:
    candidates = [
        "▶ 제안이유 및 주요내용",
        "대안의 제안이유 및 주요내용",
        "제안이유 및 주요내용",
    ]

    starts = []
    for candidate in candidates:
        pos = 0
        while True:
            idx = page_text.find(candidate, pos)
            if idx < 0:
                break
            starts.append((idx, candidate))
            pos = idx + len(candidate)

    if not starts:
        return ""

    # 제목/메뉴에 같은 문구가 한 번 더 등장하는 페이지가 있어 마지막 출현을 본문 시작점으로 사용한다.
    start, marker = max(starts, key=lambda x: x[0])
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

    # 국민참여입법센터는 두 항목을 한 본문으로 제공하는 경우가 많다.
    # 대부분 문제/현황 설명 뒤 "이에 ..."로 실제 개정내용이 시작된다.
    pivot = re.search(r"(?:^|\n|\s)(이에(?:\s+따라)?\s+)", text)
    if pivot and pivot.start() > 40:
        reason = clean_inline(text[: pivot.start()])
        main = clean_inline(text[pivot.start():])
        return {"proposal_reason": reason, "main_content": main}

    return {"proposal_reason": "", "main_content": clean_inline(text)}


def _extract_from_lawmaking_html(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # 표 형식: <th>제안이유 및 주요내용</th><td>본문...</td>
    for label in soup.find_all(["th", "dt", "strong", "span", "div"]):
        label_text = clean_inline(label.get_text(" ", strip=True))
        if label_text != "제안이유 및 주요내용":
            continue

        if label.name == "th":
            td = label.find_next_sibling("td")
            if td:
                body = clean_inline(td.get_text("\n", strip=True))
                if len(body) >= 30:
                    return _split_reason_main(body)
        if label.name == "dt":
            dd = label.find_next_sibling("dd")
            if dd:
                body = clean_inline(dd.get_text("\n", strip=True))
                if len(body) >= 30:
                    return _split_reason_main(body)

        parent = label.parent
        if parent:
            text = clean_inline(parent.get_text("\n", strip=True))
            if len(text) >= 50:
                segment = _extract_relevant_segment(text)
                if segment:
                    return _split_reason_main(segment)

    page_text = clean_inline(soup.get_text("\n", strip=True))
    segment = _extract_relevant_segment(page_text)
    return _split_reason_main(segment)


def _get_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    return response.text


def fetch_bill_content(bill: Dict, session: Optional[requests.Session] = None) -> Dict[str, str]:
    own_session = session is None
    session = session or requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/151 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
        }
    )

    errors = []
    try:
        # 1순위: 국민참여입법센터. 의안번호 기반이며 본문 텍스트가 정적 HTML에 노출된다.
        lawmaking_url = build_lawmaking_url(bill)
        if lawmaking_url:
            try:
                parts = _extract_from_lawmaking_html(_get_html(session, lawmaking_url))
                if parts["proposal_reason"] or parts["main_content"]:
                    return {
                        **parts,
                        "content_source": "국민참여입법센터",
                        "content_error": "",
                    }
                errors.append("국민참여입법센터: 제안이유 및 주요내용 영역을 찾지 못했습니다.")
            except Exception as exc:
                errors.append(f"국민참여입법센터: {exc}")

        # 2순위 fallback: LIKMS 상세페이지
        likms_url = build_detail_url(bill)
        if likms_url:
            try:
                soup = BeautifulSoup(_get_html(session, likms_url), "html.parser")
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                raw_text = clean_inline(soup.get_text("\n", strip=True))
                parts = _split_reason_main(_extract_relevant_segment(raw_text))
                if parts["proposal_reason"] or parts["main_content"]:
                    return {
                        **parts,
                        "content_source": "LIKMS",
                        "content_error": "",
                    }
                errors.append("LIKMS: 제안이유 및 주요내용 영역을 찾지 못했습니다.")
            except Exception as exc:
                errors.append(f"LIKMS: {exc}")

        return {
            "proposal_reason": "",
            "main_content": "",
            "content_source": "",
            "content_error": " / ".join(errors) or "원문 수집 경로가 없습니다.",
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
                f"source={content.get('content_source') or '-'}",
                f"reason={len(content.get('proposal_reason', ''))}",
                f"main={len(content.get('main_content', ''))}",
                f"error={content.get('content_error') or '-'}",
            )
    finally:
        session.close()
