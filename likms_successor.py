import re
from typing import Dict, List, Tuple

import requests
from bs4 import BeautifulSoup

LIKMS_DETAIL_URL = "https://likms.assembly.go.kr/bill/bi/billDetailPage.do"


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _headers() -> Dict[str, str]:
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def fetch_likms_successor_bill_ids(
    session: requests.Session,
    original_bill_id: str,
) -> Tuple[List[str], List[str]]:
    """Return explicit successor BILL_ID values exposed by LIKMS.

    For bills disposed as 대안반영폐기, the official LIKMS detail page includes
    `selRefBillId`, which directly references the committee alternative. This is
    stronger and more stable than parsing HWP tables or ranking nearby candidates.
    """
    original_bill_id = clean(original_bill_id)
    if not original_bill_id:
        return [], []

    response = session.get(
        LIKMS_DETAIL_URL,
        params={"billId": original_bill_id, "currMenuNo": "2600044"},
        headers=_headers(),
        timeout=30,
        allow_redirects=True,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")

    ids = []
    seen = set()
    for tag in soup.find_all("input"):
        name = clean(tag.get("name"))
        if name != "selRefBillId":
            continue
        value = clean(tag.get("value"))
        if not value or value == original_bill_id or value in seen:
            continue
        seen.add(value)
        ids.append(value)

    print(f"[INFO] LIKMS selRefBillId 관계: {original_bill_id} -> {ids or '-'}")
    return ids, [response.url]
