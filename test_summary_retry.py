import unittest
from unittest.mock import patch
import requests
import content_enrichment as c
import telegram_enriched_runner as runner
from test_mobile_summary import VALID, response
SOURCE='제안이유 현행법은 가맹점사업자의 계약해지 요구 절차가 없어 이를 보완하려는 것임. 주요내용 가. 묵시적 갱신 사전 통지 의무화. 나. 귀책 없이 예견하기 어려운 사정으로 영업 지속이 현저히 곤란하면 해지 요청 허용, 14일 이내 통지 및 실제 손실 초과 위약금 금지.'
class Tests(unittest.TestCase):
 @patch.dict('os.environ',{'GEMINI_API_KEY':'test'})
 @patch.object(c.requests,'post',return_value=response(VALID))
 def test_combined_main_only_calls_ai(self,post):
  self.assertTrue(c.summarize_bill_with_ai({},'',SOURCE)['aiUsed'])
  self.assertEqual(post.call_count,1)
  self.assertIn(SOURCE,post.call_args.kwargs['json']['contents'][0]['parts'][0]['text'])
 @patch.dict('os.environ',{'GEMINI_API_KEY':'test'})
 @patch.object(c.requests,'post',return_value=response(VALID))
 def test_reason_only_calls_ai(self,post):
  self.assertTrue(c.summarize_bill_with_ai({},SOURCE,'')['aiUsed'])
 @patch.dict('os.environ',{'GEMINI_API_KEY':'test'})
 @patch.object(c.time,'sleep')
 @patch.object(c,'_gemini_models',return_value=['gemini-3.8-flash','gemini-3.6-flash','gemini-3.5-flash'])
 @patch.object(c.requests,'post')
 def test_reaches_last_model(self,post,models,sleep):
  post.side_effect=[requests.HTTPError('503')]*4+[response(VALID)]
  self.assertEqual(c.summarize_bill_with_ai({},'',SOURCE)['aiModel'],'gemini-3.5-flash')
 @patch.dict('os.environ',{'GEMINI_API_KEY':'test'})
 @patch.object(c.time,'sleep')
 @patch.object(c.requests,'post',side_effect=requests.HTTPError('503'))
 def test_all_fail_no_raw_fallback(self,post,sleep):
  with self.assertRaisesRegex(RuntimeError,'SUMMARY_NOT_READY'):c.summarize_bill_with_ai({},'',SOURCE)
 @patch.object(runner,'_rollback_seen_for_failed_delivery')
 @patch.object(runner.hub_notify,'send_new_bills')
 @patch.object(runner,'enrich_bills',side_effect=[RuntimeError('SUMMARY_NOT_READY'),None])
 def test_one_failure_does_not_block_next(self,enrich,send,rollback):
  bad={'bill_id':'A','bill_no':'1'}; good={'bill_id':'B','bill_no':'2'}
  with self.assertRaisesRegex(RuntimeError,'DELIVERY_PENDING'):runner.enrich_and_send_to_hub([bad,good])
  rollback.assert_called_once_with([bad]);send.assert_called_once_with([good])
if __name__=='__main__':unittest.main()
