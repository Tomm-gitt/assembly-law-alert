import copy
import unittest
from unittest.mock import patch
import lifecycle_delivery as d
import status_alert_runner as runner
import status_monitor as sm

NOW='2026-09-30T11:30:00+09:00'
BID='PRC_M2K6K0J8K0I5Q1R5P2Q4O3O7N9J0J8'
def entry():
    return {'bill_no':'2221426','bill_name':'표시·광고의 공정화에 관한 법률 일부개정법률안',
            'proposal_date':'2026-09-17','matched_law':'표시·광고의 공정화에 관한 법률',
            'lifecycle':{'committee':'정무위원회','committee_referral_date':'2026-09-18',
                         'detail_link':'https://likms.assembly.go.kr/bill/billDetail.do?billId='+BID}}
def alert(e):return {**e,'bill_id':BID,'stage':'소관위원회 회부'}
def ack(p,outcome='APPLIED'):
    return {'ok':True,'lifecycleReceipt':{'version':d.VERSION,'systemKey':'국회|'+p['sourceId'],
            'eventKey':d.event_key(p),'outcome':outcome,'projectionsConsistent':True}}
class LifecycleTests(unittest.TestCase):
    def test_verified_date_not_execution_date(self):
        self.assertEqual(d.payload_for(alert(entry()))['stageDate'],'2026-09-18')
    def test_missing_date_fails_closed(self):
        e=entry();e['lifecycle']['committee_referral_date']=''
        with self.assertRaises(ValueError):d.payload_for(alert(e))
    def test_ambiguous_reply_keeps_durable_event_then_retries(self):
        e=entry();seen={BID:e};d.enqueue(e,alert(e),NOW);saved=[]
        key=list(e['hub_lifecycle_outbox'])
        def fail(p):raise RuntimeError('HTTP 200 HTML ACK lost')
        self.assertEqual(d.flush(seen,NOW,fail,lambda s:saved.append(copy.deepcopy(s))),['2221426'])
        self.assertTrue(saved[0][BID]['hub_lifecycle_outbox'])
        self.assertEqual(key,list(e['hub_lifecycle_outbox']))
        self.assertEqual(d.flush(seen,NOW,ack,lambda s:None),[])
        self.assertFalse(e['hub_lifecycle_outbox']);self.assertTrue(e['hub_lifecycle_receipts'])
    def test_observed_state_is_not_ack(self):
        e=entry();d.enqueue(e,alert(e),NOW)
        self.assertTrue(e['hub_lifecycle_outbox']);self.assertFalse(e['hub_lifecycle_receipts'])
    def test_bad_receipts_never_clear_outbox(self):
        for mode in ['plain','eventKey','version','projectionsConsistent']:
            e=entry();d.enqueue(e,alert(e),NOW)
            def bad(p):
                r=ack(p)
                if mode=='plain':return {'ok':True}
                r['lifecycleReceipt'][mode]=False if mode=='projectionsConsistent' else 'wrong'
                return r
            self.assertTrue(d.flush({BID:e},NOW,bad,lambda s:None));self.assertTrue(e['hub_lifecycle_outbox'])
    def test_unchanged_snapshot_reconciles_each_day(self):
        e=entry();d.enqueue(e,alert(e),NOW);d.flush({BID:e},NOW,ack,lambda s:None)
        d.enqueue(e,alert(e),NOW);self.assertFalse(e['hub_lifecycle_outbox'])
        d.enqueue(e,alert(e),'2026-10-01T06:34:00+09:00');self.assertEqual(len(e['hub_lifecycle_outbox']),1)
    def test_failure_does_not_block_other_bill(self):
        a=entry();b=entry();d.enqueue(a,alert(a),NOW);d.enqueue(b,{**alert(b),'bill_id':'B'},NOW)
        def post(p):
            if p['sourceId']==BID:raise RuntimeError('unavailable')
            return ack(p)
        self.assertEqual(d.flush({BID:a,'B':b},NOW,post,lambda s:None),['2221426'])
        self.assertFalse(b['hub_lifecycle_outbox'])
    def test_superseded_ack(self):
        e=entry();d.enqueue(e,alert(e),NOW)
        self.assertFalse(d.flush({BID:e},NOW,lambda p:ack(p,'SUPERSEDED'),lambda s:None))
    def test_retry_payload_is_immutable(self):
        e=entry();d.enqueue(e,alert(e),NOW);old=copy.deepcopy(e['hub_lifecycle_outbox'])
        e['bill_name']='changed';d.enqueue(e,alert(e),'2026-10-01T06:00:00+09:00')
        self.assertEqual(old,e['hub_lifecycle_outbox'])
    def run_main(self,e,post):
        snap=copy.deepcopy(e.get('lifecycle') or entry()['lifecycle'])
        with patch.object(sm.monitor,'load_seen',return_value={BID:e}),patch.object(sm.monitor,'save_seen'),patch.object(sm,'fetch_lifecycle',return_value=snap),patch('hub_notify._post',side_effect=post):
            return runner.main()
    def test_first_snapshot_already_referred_incident(self):
        e=entry();e.pop('lifecycle');calls=[]
        self.run_main(e,lambda p:(calls.append(p) or ack(p)))
        self.assertEqual(len(calls),1);self.assertEqual(calls[0]['stageDate'],'2026-09-18')
    def test_existing_snapshot_missing_hub_receipt(self):
        e=entry();e['lifecycle_initialized_at']='2026-09-21T06:34:42+09:00';calls=[]
        self.run_main(e,lambda p:(calls.append(p) or ack(p)))
        self.assertEqual(len(calls),1)
    def test_delivery_failure_after_observation_retries(self):
        e=entry()
        def fail(p):raise RuntimeError('lost reply')
        with self.assertRaisesRegex(RuntimeError,'PARTIAL_FAILURE'):self.run_main(e,fail)
        self.assertTrue(e['hub_lifecycle_outbox']);self.run_main(e,ack);self.assertFalse(e['hub_lifecycle_outbox'])
    def test_unknown_hub_baseline_ack_is_checked_again_next_day(self):
        e=entry();d.enqueue(e,alert(e),NOW)
        def missing(p):
            r=ack(p,'NOT_REGISTERED');r['lifecycleReceipt'].update(registered=False,projectionsConsistent=False);return r
        self.assertFalse(d.flush({BID:e},NOW,missing,lambda s:None));self.assertFalse(e['hub_lifecycle_outbox'])
        d.enqueue(e,alert(e),'2026-10-01T06:34:00+09:00');self.assertTrue(e['hub_lifecycle_outbox'])
    def test_query_failure_still_flushes_durable_pending(self):
        e=entry();d.enqueue(e,alert(e),NOW)
        with patch.object(sm.monitor,'load_seen',return_value={BID:e}),patch.object(sm.monitor,'save_seen'),patch.object(sm,'fetch_lifecycle',side_effect=RuntimeError('API unavailable')),patch('hub_notify._post',side_effect=ack):
            with self.assertRaisesRegex(RuntimeError,'PARTIAL_FAILURE'):runner.main()
        self.assertFalse(e['hub_lifecycle_outbox'])
if __name__=='__main__':unittest.main()
