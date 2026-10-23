"""Replay only pre-baseline pending receipts through the silent HUB repair endpoint.
No collector querying, notification dispatch, or persisted state edits.
"""
import copy
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import lifecycle_delivery as delivery
import hub_notify
import monitor

EXPECTED_HUB_BUILD = '123e24d72ee4ad9b09515be919cb9a10c215c447'

def main():
    response=requests.post(hub_notify._hub_url(),json={'lifecycleIdentityHealthcheck':True},timeout=120)
    response.raise_for_status()
    health=hub_notify._parse_hub_response(response)
    assert health.get('build')==EXPECTED_HUB_BUILD and health.get('identityResolver')=='2026-10-23-v1'
    seen=monitor.load_seen()
    selected={bid:copy.deepcopy(e) for bid,e in seen.items() if e.get('hub_lifecycle_outbox')}
    pending={bid:list(e['hub_lifecycle_outbox']) for bid,e in selected.items()}
    for bid,e in selected.items():
        assert e.get('historical_baseline')=='HISTORICAL_O_BASELINE_20261021'
        cutoff=e['historical_baseline_initialized_at'][:10]
        for key,item in e['hub_lifecycle_outbox'].items():
            p=item['payload']
            assert p['sourceId']==bid and str(p['billNo'])==str(e['bill_no'])
            assert key==delivery.event_key(p) and p['stageDate']<=cutoff
    def post(p):
        return hub_notify._post({**p,'action':'repair-historical-lifecycle'})
    failures=delivery.flush(selected,datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds'),post,lambda s:None)
    results=[]
    for bid,e in selected.items():
        for key in pending[bid]:
            if key not in e['hub_lifecycle_outbox']:
                results.append({'sourceId':bid,'billNo':e['bill_no'],'eventKey':key,'receipt':e['hub_lifecycle_receipts'][key]})
    print('SILENT_REPLAY_RECEIPTS='+json.dumps(results,ensure_ascii=False))
    print('SILENT_REPLAY_SUMMARY='+json.dumps({'requested':sum(map(len,pending.values())),'acknowledged':len(results),'failures':failures}))
    if failures: raise SystemExit(1)

if __name__=='__main__': main()
