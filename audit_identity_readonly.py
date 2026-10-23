"""Read official identifier mappings only. No HUB, state writes or notification transports."""
import concurrent.futures
import json
import os
import requests
from pathlib import Path


def lookup(bid):
    for endpoint, age in [('nzmimeepazxkubdpn', {'AGE': '22'}), ('BILLRCP', {})]:
        try:
            response = requests.get('https://open.assembly.go.kr/portal/openapi/' + endpoint,
                params={'KEY': os.environ['ASSEMBLY_API_KEY'], 'Type': 'json', 'pIndex': 1,
                        'pSize': 100, 'BILL_ID': bid, **age}, timeout=30)
            response.raise_for_status()
            data = response.json()
            rows = [r for section in data.get(endpoint, []) if isinstance(section, dict) for r in section.get('row', [])]
            matches = {str(r['BILL_NO']) for r in rows if r.get('BILL_ID') == bid and r.get('BILL_NO')}
            if len(matches) == 1:
                return {'sourceId': bid, 'billNo': matches.pop(), 'endpoint': endpoint}
        except Exception:
            pass  # Never emit request URLs containing credentials.
    return {'sourceId': bid, 'error': 'NO_UNIQUE_VERIFIED_MAPPING'}

if __name__ == '__main__':
    ids = json.loads(Path('tests/identity-audit-ids.json').read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        result = list(pool.map(lookup, ids))
    Path('identity-audit-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print('IDENTITY_AUDIT_JSON=' + json.dumps(result, ensure_ascii=False))
