"""Offline regressions: legacy entrypoints cannot bypass HUB; acknowledgments fail closed."""
import unittest
from unittest.mock import patch, Mock
import hub_notify
import telegram_notify

class NotificationContractTests(unittest.TestCase):
    def test_legacy_entrypoints_use_hub(self):
        self.assertIs(telegram_notify.send_status_alerts, hub_notify.send_status_alerts)
        self.assertIs(telegram_notify.send_new_bills, hub_notify.send_new_bills)
        with self.assertRaises(RuntimeError):
            telegram_notify._send('must not send')

    @patch('hub_notify.time.sleep')
    @patch('hub_notify.requests.post')
    def test_failure_never_acknowledged(self, post, sleep):
        response=Mock(status_code=200, text='<html>Error</html>')
        response.json.side_effect=ValueError('not json')
        post.return_value=response
        with self.assertRaises(RuntimeError):hub_notify._post({'sourceId':'A'})
        self.assertEqual(post.call_count,3)

    @patch('hub_notify._post')
    def test_stopped_item_is_excluded_after_recording(self, post):
        post.return_value={'ok':True,'action':'ASSEMBLY_TRACKING_STOPPED'}
        self.assertEqual(hub_notify.send_status_alerts([{'bill_id':'A','stage':'공포','stage_date':'2026-09-23'}]),[])
        self.assertEqual(post.call_count,1)
        self.assertEqual(post.call_args.args[0]['sourceId'],'A')

    def test_identity_preserved_for_successor(self):
        p=hub_notify.build_status_payload({'bill_id':'successor','hub_source_id':'original','stage':'시행','stage_date':'2026-10-01'})
        self.assertEqual(p['sourceId'],'original')
        self.assertEqual(p['stageDate'],'2026-10-01')

if __name__=='__main__':unittest.main()
