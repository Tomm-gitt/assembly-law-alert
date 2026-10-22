import sys,types,unittest
sys.modules.setdefault('monitor',types.SimpleNamespace(save_seen=lambda x:None))
try:
 import requests
except ImportError:
 sys.modules['requests']=types.SimpleNamespace()
import hub_notify,lifecycle_delivery
class ReportRelationshipTest(unittest.TestCase):
 def test_alternative_own_identity(self):
  p=hub_notify.build_status_payload(dict(bill_id='ALT',hub_source_id='ORIG',bill_no='2219999',origin_bill_nos=['2200001'],successor_relationship_source='likms_selRefBillId',stage='발의/접수',proposal_date='2026-10-22'))
  self.assertEqual(p['sourceId'],'ALT');self.assertEqual(p['alternativeOrigins'],['2200001'])
 def test_disposal_actual_date(self):
  p=lifecycle_delivery.payload_for(dict(bill_id='ORIG',bill_no='2200001',proposal_date='2024-06-01',stage='위원회 대안 자동승계',alternative_reflection={'result':'대안반영폐기'},lifecycle={'committee_process_result':'대안반영폐기','committee_process_date':'2026-10-20'},last_status_checked_at='2026-10-22'))
  self.assertEqual(p['stageDate'],'2026-10-20');self.assertEqual(p['currentStage'],'대안반영폐기')
 def test_missing_date_not_detection_date(self):
  with self.assertRaises(ValueError):
   lifecycle_delivery.payload_for(dict(stage='위원회 대안 자동승계',alternative_reflection={'result':'대안반영폐기'},last_status_checked_at='2026-10-22'))
if __name__=='__main__':unittest.main()
