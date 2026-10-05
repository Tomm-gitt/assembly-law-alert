import json, unittest
from unittest.mock import patch, Mock
import content_enrichment as c

VALID={'reason':'반복 담합에 대한 제재와 불법상태 해소 수단을 보완하고 처분시효를 연장하여 담합 억지력 강화.', 'mainItems':['담합이 없었을 경우의 경쟁 회복 수준으로 가격을 재결정하도록 시정조치 유형 명시.','담합 처분일부터 5년 이내 재담합으로 2회 이상 처분 시 등록취소 또는 6개월 이내 영업정지 요청 근거 신설. 관계 행정기관은 정당한 사유가 없으면 이행.','자진신고자 감면 대상에서 시정조치 제외.','담합 처분시효를 조사 개시 시 개시일부터 10년, 미개시 시 위반행위 종료일부터 10년으로 연장.']}
def response(v,finish='STOP'):
 r=Mock();r.json.return_value={'candidates':[{'finishReason':finish,'content':{'parts':[{'text':json.dumps(v)}]}}]};return r
class Tests(unittest.TestCase):
 def test_valid_conditions(self):
  c.validate_mobile_summary(VALID)
  text=c.build_collector_content(VALID['reason'],VALID['mainItems'])
  for term in ['5년','2회','6개월','10년','정당한 사유','조사 개시','종료일']:self.assertIn(term,text)
 def test_reject_long_reason(self):
  with self.assertRaisesRegex(ValueError,'TOO_LONG'):c.validate_mobile_summary(dict(VALID,reason='설명'*100+'.'))
 def test_no_item_count_cap(self):c.validate_mobile_summary(dict(VALID,mainItems=VALID['mainItems']*3))
 def test_truncated(self):
  with self.assertRaisesRegex(ValueError,'INCOMPLETE'):c.validate_mobile_summary(dict(VALID,reason='설명을 줄여…'))
 @patch.dict('os.environ',{'GEMINI_API_KEY':'test'})
 @patch.object(c.time,'sleep')
 @patch.object(c.requests,'post')
 def test_retry_verbose(self,post,sleep):
  post.side_effect=[response(dict(VALID,reason='설명'*100+'.')),response(VALID)]
  result=c.summarize_bill_with_ai({},'source','source')
  self.assertTrue(result['aiUsed']);self.assertEqual(result['mainItems'],VALID['mainItems']);self.assertEqual(post.call_count,2)
 @patch.dict('os.environ',{'GEMINI_API_KEY':'test'})
 @patch.object(c.time,'sleep')
 @patch.object(c.requests,'post')
 def test_token_cutoff_retry(self,post,sleep):
  post.side_effect=[response(VALID,'MAX_TOKENS'),response(VALID)]
  self.assertTrue(c.summarize_bill_with_ai({},'source','source')['aiUsed']);self.assertEqual(post.call_count,2)
if __name__=='__main__':unittest.main()
