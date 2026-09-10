import json
import os
import re
import time
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

ASSEMBLY_GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
]
AI_SOURCE_MAX_LENGTH = 14000


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


def _find_combined_section_pivot(text: str):
    preferred_patterns = [
        r"(?:^|\n|\s)(이에\s+(?:따라\s+)?(?:본\s*)?(?:개정안|법률안)(?:은|에서는|으로|을|를)?\s*)",
        r"(?:^|\n|\s)(따라서\s+(?:본\s*)?(?:개정안|법률안)(?:은|에서는|으로|을|를)?\s*)",
    ]
    for pattern in preferred_patterns:
        match = re.search(pattern, text)
        if match and match.start() > 40:
            return match
    generic = re.search(
        r"(?:^|\n|\s)(이에(?:\s+따라)?\s+(?=(?:현행법|법|제\d+조|규정|근거|제도|절차|권한|의무|과태료|벌칙).{0,80}(?:개정|신설|삭제|마련|규정|부과|강화|개선)))",
        text,
        flags=re.S,
    )
    if generic and generic.start() > 40:
        return generic
    return None


def _split_reason_main(segment: str) -> Dict[str, str]:
    if not segment:
        return {"proposal_reason": "", "main_content": ""}
    text = re.sub(
        r"^(?:제안이유 및 주요내용|대안의 제안이유 및 주요내용)\s*",
        "",
        segment,
    ).strip()
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
        return {
            "proposal_reason": clean_inline(reason_match.group(1) if reason_match else ""),
            "main_content": clean_inline(main_match.group(1) if main_match else ""),
        }
    pivot = _find_combined_section_pivot(text)
    if pivot:
        return {
            "proposal_reason": clean_inline(text[: pivot.start()]),
            "main_content": clean_inline(text[pivot.start():]),
        }
    return {"proposal_reason": "", "main_content": clean_inline(text)}


def _extract_from_lawmaking_html(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
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
            parent_text = clean_inline(parent.get_text("\n", strip=True))
            if len(parent_text) >= 50:
                segment = _extract_relevant_segment(parent_text)
                if segment:
                    return _split_reason_main(segment)
    page_text = clean_inline(soup.get_text("\n", strip=True))
    return _split_reason_main(_extract_relevant_segment(page_text))


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
        lawmaking_url = build_lawmaking_url(bill)
        if lawmaking_url:
            try:
                parts = _extract_from_lawmaking_html(_get_html(session, lawmaking_url))
                if parts["proposal_reason"] or parts["main_content"]:
                    return {**parts, "content_source": "국민참여입법센터", "content_error": ""}
                errors.append("국민참여입법센터: 제안이유 및 주요내용 영역을 찾지 못했습니다.")
            except Exception as exc:
                errors.append(f"국민참여입법센터: {exc}")
        likms_url = build_detail_url(bill)
        if likms_url:
            try:
                soup = BeautifulSoup(_get_html(session, likms_url), "html.parser")
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                raw_text = clean_inline(soup.get_text("\n", strip=True))
                parts = _split_reason_main(_extract_relevant_segment(raw_text))
                if parts["proposal_reason"] or parts["main_content"]:
                    return {**parts, "content_source": "LIKMS", "content_error": ""}
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


def _gemini_models() -> List[str]:
    configured = str(os.getenv("ASSEMBLY_GEMINI_MODEL") or "").strip()
    models: List[str] = []
    for model in [configured, *ASSEMBLY_GEMINI_MODELS]:
        name = str(model or "").strip()
        if name and name not in models:
            models.append(name)
    return models


def _build_ai_prompt(bill: Dict, reason: str, main: str) -> str:
    return f"""
당신은 대한민국 기업의 국회 법률안 모니터링 담당자를 지원하는 요약 도우미입니다.

아래 내용은 국회에 제출된 법률안의 제안이유와 주요내용 원문입니다.

목적:
담당자가 모바일에서 빠르게 읽고 법률안의 실제 변경사항을 판단할 수 있도록 짧고 정확하게 정리하십시오.

중요 규칙:
1. 원문에 없는 사실, 효과, 시행일, 의무를 추론하거나 추가하지 마십시오.
2. 자사 관련 여부 자체는 판단하지 마십시오.
3. 제안이유는 핵심 배경과 입법 목적을 1~3문장으로 요약하십시오.
4. 주요내용은 서로 다른 실제 변경사항을 빠뜨리지 말고 번호형 항목으로 정리하십시오.
5. 신설·삭제·변경되는 의무, 금지, 기준, 절차, 적용대상, 비용, 과태료·벌칙, 시행일·경과조치가 원문에 있으면 반드시 포함하십시오.
6. 원문 항목이 1개면 1개만, 여러 개면 핵심사항 수에 맞게 최대 7개까지 작성하십시오.
7. 제목만 다시 말하지 말고 실제 법률안 내용을 우선하십시오.
8. 응답은 반드시 JSON 객체만 반환하십시오.
9. reason과 mainItems 외 설명, 마크다운, 코드블록을 출력하지 마십시오.

법률안명:
{str(bill.get("bill_name") or "")}

관리 법률:
{str(bill.get("matched_law") or "")}

원문 제안이유:
{clean_inline(reason)[:AI_SOURCE_MAX_LENGTH] or "(별도 제안이유 없음)"}

원문 주요내용:
{clean_inline(main)[:AI_SOURCE_MAX_LENGTH] or "(주요내용 확인 불가)"}
""".strip()


def _parse_gemini_json(text: str) -> Dict:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def summarize_bill_with_ai(bill: Dict, reason: str, main: str) -> Dict:
    api_key = str(os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return {
            "reason": summarize_reason(reason),
            "mainItems": main_content_points(main),
            "aiUsed": False,
            "aiModel": "",
        }

    prompt = _build_ai_prompt(bill, reason, main)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1000,
            "responseMimeType": "application/json",
        },
    }
    last_error = None
    for model in _gemini_models():
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(1, 3):
            try:
                print("[INFO] 국회 Gemini 요약 시도:", model, f"attempt={attempt}")
                response = requests.post(
                    url,
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=45,
                )
                response.raise_for_status()
                result = response.json()
                candidates = result.get("candidates") if isinstance(result, dict) else None
                if not candidates:
                    raise RuntimeError("Gemini candidate 없음")
                parts = candidates[0].get("content", {}).get("parts", [])
                response_text = "\n".join(
                    str(part.get("text") or "") for part in parts if isinstance(part, dict)
                ).strip()
                parsed = _parse_gemini_json(response_text)
                ai_reason = clean_inline(parsed.get("reason"))
                ai_items = [
                    clean_inline(item)
                    for item in (parsed.get("mainItems") or [])
                    if clean_inline(item)
                ]
                if not ai_reason or not ai_items:
                    raise RuntimeError("Gemini 요약 JSON 형식 오류")
                print("[INFO] 국회 Gemini 요약 성공:", model)
                return {
                    "reason": ai_reason,
                    "mainItems": ai_items,
                    "aiUsed": True,
                    "aiModel": model,
                }
            except Exception as exc:
                last_error = exc
                print(
                    "[WARN] 국회 Gemini 요약 실패:",
                    model,
                    f"attempt={attempt}",
                    str(exc)[:500],
                )
                if attempt < 2:
                    time.sleep(1.5 * attempt)

    print("[WARN] 모든 Gemini 모델 실패 - 비AI fallback 사용:", str(last_error)[:500])
    return {
        "reason": summarize_reason(reason),
        "mainItems": main_content_points(main),
        "aiUsed": False,
        "aiModel": "",
    }


def build_collector_content(reason: str, main_items: List[str]) -> str:
    lines: List[str] = []
    reason = clean_inline(reason)
    items = [clean_inline(item) for item in (main_items or []) if clean_inline(item)]
    if reason:
        lines.extend(["■ 제안이유", reason])
    if items:
        if lines:
            lines.append("")
        lines.append("■ 주요내용")
        for index, item in enumerate(items, 1):
            lines.append(f"{index}. {item}")
    return "\n".join(lines).strip()


def enrich_bill(bill: Dict, session: Optional[requests.Session] = None) -> Dict:
    content = fetch_bill_content(bill, session=session)
    bill.update(content)
    summary = summarize_bill_with_ai(
        bill,
        content.get("proposal_reason", ""),
        content.get("main_content", ""),
    )
    bill["proposal_reason_summary"] = summary.get("reason") or ""
    bill["main_content_points"] = summary.get("mainItems") or []
    bill["ai_used"] = summary.get("aiUsed") is True
    bill["ai_model"] = summary.get("aiModel") or ""
    bill["content"] = build_collector_content(
        bill["proposal_reason_summary"],
        bill["main_content_points"],
    )
    return bill


def enrich_bills(bills: List[Dict]) -> None:
    session = requests.Session()
    try:
        for bill in bills:
            enrich_bill(bill, session=session)
            print(
                "[INFO] 국회 원문/AI 처리",
                bill.get("bill_no"),
                f"source={bill.get('content_source') or '-'}",
                f"reason={len(bill.get('proposal_reason', ''))}",
                f"main={len(bill.get('main_content', ''))}",
                f"ai={bill.get('ai_used')}",
                f"model={bill.get('ai_model') or '-'}",
                f"content={len(bill.get('content', ''))}",
                f"error={bill.get('content_error') or '-'}",
            )
    finally:
        session.close()


def test_ai_summary_only() -> Dict:
    bill = {
        "bill_name": "[TEST] 독점규제 및 공정거래에 관한 법률 일부개정법률안",
        "matched_law": "독점규제 및 공정거래에 관한 법률",
    }
    reason = "현행 제도의 운영상 미비점을 개선하고 사업자의 예측가능성을 높이기 위하여 관련 규정을 정비하려는 것임."
    main = (
        "가. 자료 제출 기준을 명확히 함.\n"
        "나. 반복 위반에 대한 기준을 정비함.\n"
        "다. 시행일과 적용례를 규정함."
    )
    result = summarize_bill_with_ai(bill, reason, main)
    result["content"] = build_collector_content(
        result.get("reason", ""), result.get("mainItems", [])
    )
    return result


if __name__ == "__main__":
    print(json.dumps(test_ai_summary_only(), ensure_ascii=False, indent=2))
