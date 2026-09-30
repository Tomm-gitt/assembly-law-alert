"""Durable HUB outbox, separate from observed Assembly lifecycle snapshots."""
import hub_notify
import monitor

VERSION = '2026-09-30-v1'
STAGE_FIELDS = {
    '소관위원회 회부': 'committee_referral_date',
    '소관위원회 상정': 'committee_present_date',
    '소관위원회 처리': 'committee_process_date',
    '법제사법위원회 회부': 'law_submit_date',
    '법제사법위원회 상정': 'law_present_date',
    '법제사법위원회 처리': 'law_process_date',
    '본회의 처리': 'plenary_date',
    '정부이송': 'government_transfer_date',
}

def payload_for(alert):
    stage = alert['stage']
    snapshot = alert.get('lifecycle') or {}
    date = alert.get('stage_date') or snapshot.get(STAGE_FIELDS.get(stage, ''))
    if not date and stage == '발의/접수':
        date = alert.get('proposal_date')
    if not date:
        # Special successor notices have an observation date, never invent a referral date.
        if stage in STAGE_FIELDS:
            raise ValueError('Missing verified stage date: ' + stage)
        date = str(alert.get('last_status_checked_at') or '')[:10]
    if not date:
        raise ValueError('Missing lifecycle event date')
    p = hub_notify.build_status_payload({**alert, 'stage_date': date})
    p['lifecycleSync'] = VERSION
    return p

def event_key(p):
    return '|'.join(['ASSEMBLY_STAGE', p['sourceOrg']+'|'+p['sourceId'], p['currentStage'], p['stageDate']])

def enqueue(entry, alert, now, force=False):
    p = payload_for(alert)
    key = event_key(p)
    receipts = entry.setdefault('hub_lifecycle_receipts', {})
    receipt = receipts.get(key, {})
    # Reconcile unchanged snapshots once per KST day, even after an earlier ACK.
    if not force and receipt.get('verified_at', '')[:10] == now[:10]:
        return
    pending = entry.setdefault('hub_lifecycle_outbox', {})
    if key not in pending:
        pending[key] = {'payload': p, 'created_at': now, 'attempts': 0}

def verify_receipt(result, p):
    receipt = result.get('lifecycleReceipt') or {}
    if (result.get('ok') is not True or receipt.get('version') != VERSION
            or receipt.get('systemKey') != p['sourceOrg']+'|'+p['sourceId']
            or receipt.get('eventKey') != event_key(p)
            or receipt.get('outcome') not in ('APPLIED', 'UNCHANGED', 'SUPERSEDED', 'NOT_REGISTERED')
            or not (receipt.get('projectionsConsistent') is True or
                    (receipt.get('outcome') == 'NOT_REGISTERED' and receipt.get('registered') is False))):
        raise RuntimeError('HUB lifecycle receipt missing or mismatched')
    return receipt

def flush(seen, now, post=None, save=None):
    post = post or hub_notify._post
    save = save or monitor.save_seen
    failures = []
    for bill_id, entry in seen.items():
        pending = entry.setdefault('hub_lifecycle_outbox', {})
        for key, item in list(pending.items()):
            item['attempts'] += 1
            item['last_attempt_at'] = now
            save(seen)  # durable intent before network; an ambiguous reply remains retryable
            try:
                result = post(item['payload'])
                receipt = verify_receipt(result, item['payload'])
                entry.setdefault('hub_lifecycle_receipts', {})[key] = {**receipt, 'verified_at': now}
                del pending[key]
                print(f"[INFO] HUB lifecycle ACK: {entry.get('bill_no') or bill_id} / {receipt['outcome']} / {item['payload']['currentStage']}")
            except Exception as exc:
                item['last_error'] = str(exc)[:1000]
                failures.append(entry.get('bill_no') or bill_id)
                print(f"[ERROR] HUB lifecycle pending: {entry.get('bill_no') or bill_id} / {exc}")
            save(seen)  # ACK only after all HUB projections + queue intent are verified
    return failures
