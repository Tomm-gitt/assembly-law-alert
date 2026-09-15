import json
from datetime import date

import requests

import monitor

TARGET_IDS = [
    "PRC_V2X6R0E5I1T3Z1P7I5O7R0R2Q2R5T1",
    "PRC_B2V6Z0J5V1C3M1O7N5P7Z3R9W8T0A1",
    "PRC_O2O6M0N8L1M8U1U1T0R0S5Q2Q4Z5Z0",
    "PRC_X2X6W0W8V0T7U1C7C2A4Z3A3Y7Z6H5",
    "PRC_R2P6P0O8P2K5L1J5H4I1G2H8P5P1O0",
    "PRC_I2J6I0I8D3C1D1B5B1A9B5I7J3I0G0",
    "PRC_T2R6S0R9R0Q2X1Y3X2X0V2U5U0C8D9",
    "PRC_B2C6A0B9J0J2I0G9H3F5G5V6V4T2S6",
    "PRC_D2E6C0B9B0X7X1W3X4V4V1T7C7C2A2",
    "PRC_M2L6L0K9K0S8R1R9P1Q7P0P4X6V8W9",
]


def clean(value):
    return str(value or "").strip()


def receipt_rows(session):
    rows = []
    for page in range(1, 11):
        data = monitor.request_api(
            session,
            monitor.RECEIPT_API,
            {"pIndex": str(page), "pSize": "1000"},
        )
        page_rows = monitor.parse_rows(data, monitor.RECEIPT_API)
        if not page_rows:
            break
        rows.extend(page_rows)
        if len(page_rows) < 1000:
            break
    return rows


def member_rows(session):
    rows = []
    for page in range(1, 11):
        data = monitor.request_api(
            session,
            monitor.MEMBER_BILLS_API,
            {"pIndex": str(page), "pSize": "1000", "AGE": monitor.AGE},
        )
        page_rows = monitor.parse_rows(data, monitor.MEMBER_BILLS_API)
        if not page_rows:
            break
        rows.extend(page_rows)
        if len(page_rows) < 1000:
            break
    return rows


def main():
    with requests.Session() as session:
        members = {clean(r.get("BILL_ID")): r for r in member_rows(session)}
        receipts = {clean(r.get("BILL_ID")): r for r in receipt_rows(session)}

    output = []
    for bill_id in TARGET_IDS:
        member = members.get(bill_id, {})
        receipt = receipts.get(bill_id, {})

        bill_no = clean(member.get("BILL_NO") or receipt.get("BILL_NO"))
        bill_name = clean(member.get("BILL_NAME") or receipt.get("BILL_NM"))
        proposer = clean(
            member.get("PROPOSER")
            or member.get("RST_PROPOSER")
            or receipt.get("PPSR_NM")
            or receipt.get("PROPOSER")
        )
        proposer_kind = clean(receipt.get("PPSR_KIND"))
        committee = clean(member.get("COMMITTEE") or receipt.get("CURR_COMMITTEE"))

        # 위원회 대안 등 개인 발의자가 없는 경우에는 제안 주체를 사람이 아닌 기관으로 기록한다.
        if not proposer and proposer_kind:
            if "위원" in proposer_kind and committee:
                proposer = committee
            else:
                proposer = proposer_kind

        output.append({
            "bill_id": bill_id,
            "bill_no": bill_no,
            "bill_name": bill_name,
            "proposer": proposer,
            "proposer_kind": proposer_kind,
            "committee": committee,
            "found_member": bool(member),
            "found_receipt": bool(receipt),
        })

    print("BACKFILL_JSON=" + json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
