"""Build a content-only Sheets request. No network, HUB, seen-state or send imports.

Caller must freshly read identity and the expected old content before applying.
Never accept row numbers alone, and never repair from a failed extraction.
"""
from content_enrichment import has_source_content, is_missing_content_claim


def build_master_content_patch(row, bill, expected_content, row_number, sheet_id):
    if len(row) < 12 or row[1] != '국회' or str(row[4]) != str(bill.get('bill_no')):
        raise ValueError('MASTER_IDENTITY_MISMATCH')
    if row[3] != bill.get('bill_name') or row[7] != expected_content:
        raise ValueError('MASTER_CHANGED')
    if bill.get('content_status') != 'EXTRACTED' or not has_source_content(bill):
        raise ValueError('NO_VERIFIED_SOURCE')
    content = bill.get('content', '').strip()
    if not content or is_missing_content_claim(content):
        raise ValueError('INVALID_REPAIR_CONTENT')
    if expected_content.strip() and not is_missing_content_claim(expected_content):
        raise ValueError('EXISTING_CONTENT_NOT_MISSING')
    if row_number < 2:
        raise ValueError('INVALID_ROW')
    # Only H is in this request, so J:L (judgment, reason, reviewer), queues,
    # lifecycle state, dates and all other cells remain untouched.
    return {'updateCells': {
        'range': {'sheetId': sheet_id, 'startRowIndex': row_number-1,
                  'endRowIndex': row_number, 'startColumnIndex': 7, 'endColumnIndex': 8},
        'rows': [{'values': [{'userEnteredValue': {'stringValue': content}}]}],
        'fields': 'userEnteredValue',
    }}
