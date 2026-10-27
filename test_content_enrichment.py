import unittest
from unittest.mock import patch, Mock
import requests
import content_enrichment as c
from content_repair import build_master_content_patch

REASON = '현행 제도의 반복 위반에 대한 제재 수단이 부족하여 개선이 필요한 상황임.'
MAIN = '공포 후 6개월부터 반복 위반 사업자에 대한 처분 기준과 적용 요건을 명확하게 정비함.'
BILL = {'bill_no': '2221860', 'bill_id': 'PRC_9DCD75E9C9C842F7B3307DB8456A6A', 'bill_name': '법률안'}
HTML = '<table><tr><th>제안 이유 및 주요 내용</th><td>제안이유<br>'+REASON+'<br>주요내용<br>'+MAIN+'</td></tr></table>'

class Tests(unittest.TestCase):
    def test_spaced_table_heading(self):
        self.assertEqual(c._extract_from_lawmaking_html(HTML), {'proposal_reason':REASON, 'main_content':MAIN})
    def test_stop_word_in_prose_not_truncated(self):
        text='제안이유 및 주요내용\n'+MAIN+'\n소관위 심사정보\nNAV'
        self.assertEqual(c._extract_relevant_segment(text),MAIN)
    def test_separate_headings(self):
        self.assertEqual(c._split_reason_main(c._extract_relevant_segment('제안 이유\n'+REASON+'\n주요 내용\n'+MAIN))['main_content'],MAIN)
    @patch.object(c, '_get_html', side_effect=['<html>navigation</html>', HTML])
    def test_secondary_source(self, get):
        result=c.fetch_bill_content(BILL, Mock())
        self.assertEqual(result['content_source'],'LIKMS')
        self.assertEqual(get.call_count,2)
    @patch.object(c, 'summarize_bill_with_ai')
    @patch.object(c, '_get_html', return_value='<html>navigation</html>')
    def test_original_incident_empty_input_never_ai(self, get, ai):
        result=c.enrich_bill(dict(BILL),Mock())
        ai.assert_not_called()
        self.assertEqual(result['content_status'],'FAILED')
        self.assertEqual(result['proposal_reason_summary'],'')
        self.assertIn('SECTION_NOT_FOUND',result['content_error'])
        self.assertIn('sha256=',result['content_error'])
        self.assertFalse(result['ai_used'])
    @patch.object(c, '_get_html', side_effect=requests.Timeout('read timeout'))
    def test_timeout_recorded(self,get):
        result=c.enrich_bill(dict(BILL),Mock())
        self.assertIn('read timeout',result['content_error'])
        self.assertEqual(result['content_status'],'FAILED')
    @patch.object(c.requests,'post')
    @patch.dict('os.environ',{'GEMINI_API_KEY':'test'})
    def test_empty_direct_summary_no_api(self,post):
        self.assertFalse(c.summarize_bill_with_ai({},'','')['aiUsed'])
        post.assert_not_called()
    @patch.dict('os.environ', {'GEMINI_API_KEY': ''})
    @patch.object(c.requests,'post')
    def test_combined_unsplit_missing_key_is_pending(self,post):
        with self.assertRaisesRegex(RuntimeError, 'SUMMARY_NOT_READY'):
            c.summarize_bill_with_ai({},'',REASON+' '+MAIN)
        post.assert_not_called()
    def test_reject_generated_absence_claim(self):
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED'):
            c.validate_mobile_summary({'reason':'제안이유가 별도로 명시되지 않아 확인할 수 없음.', 'mainItems':[MAIN]})
    def test_content_only_repair(self):
        old='제안이유가 별도로 명시되지 않아 확인할 수 없음.'
        row=['date','국회','신규', '법률안',2221860,'이강일','회부',old,'url','X','담합 관련','판정자']
        original=list(row)
        bill=dict(BILL,proposal_reason=REASON,main_content=MAIN,content_status='EXTRACTED',content=c.build_collector_content(REASON,[MAIN]))
        request=build_master_content_patch(row,bill,old,36,2027368541)['updateCells']
        self.assertEqual(request['range']['startColumnIndex'],7)
        self.assertEqual(request['range']['endColumnIndex'],8)
        self.assertEqual(row,original)
        for change,error in [({'content_status':'FAILED'},'NO_VERIFIED'),({'bill_no':'other'},'IDENTITY')]:
            with self.assertRaisesRegex(ValueError,error):build_master_content_patch(row,dict(bill,**change),old,36,2027368541)
        with self.assertRaisesRegex(ValueError,'CHANGED'):build_master_content_patch(row,bill,'stale',36,2027368541)

if __name__=='__main__':unittest.main()

