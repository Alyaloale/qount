import json
import unittest
import tempfile
import threading
import http.client
from pathlib import Path
from unittest.mock import Mock,patch
from urllib.error import URLError
from qount.research.q_div_acquisition import Collector,check_page,page_continues,quarters,specification,retryable_provider,repair_specs


class AcquisitionTests(unittest.TestCase):
    def test_incomplete_HTTP_response_is_retried_without_exporting_partial_bytes(self):
        with tempfile.TemporaryDirectory() as local:
            obj=self.collector(local);raw=self.response();value=json.loads(raw)
            obj.request=Mock(side_effect=[http.client.IncompleteRead(b'partial'),(raw,value,value['data'])])
            with patch('qount.research.q_div_acquisition.time.sleep'),patch('qount.research.q_div_acquisition.backoff',return_value=0):
                _,item=obj.fetch_page(specification('daily',{'trade_date':'20210917'}),{},0)
            self.assertEqual(item['attempt'],1);self.assertEqual(obj.sink.put.call_count,1)

    def test_repair_plan_binds_original_failed_transport_identity(self):
        spec=specification('daily',{'trade_date':'20210917'},size=6000)
        failed={**spec,'status':'failed_or_withheld','error':'IncompleteRead:broken'}
        self.assertEqual(repair_specs([failed]),[spec])
        with self.assertRaisesRegex(ValueError,'nontransient'):
            repair_specs([{**failed,'error':'ValueError:source_identity_or_period'}])
        with self.assertRaisesRegex(ValueError,'identity'):
            repair_specs([{**failed,'params':{'trade_date':'20210916'}}])

    def response(self, *, rows=None, more=False, fields=None, code=0):
        return json.dumps({'code':code,'data':{'fields':fields or ['ts_code','end_date','report_type'],
            'items':rows or [],'has_more':more}}).encode()

    def test_credential_blocks_response_before_export(self):
        with self.assertRaisesRegex(ValueError,'credential_in_response'):
            check_page(b'{"msg":"PRIVATE_TEST_VALUE"}','PRIVATE_TEST_VALUE','income_vip',{})

    def test_provider_error_can_be_preserved_without_data(self):
        value,data=check_page(b'{"code":2002,"msg":"denied"}','secret','income_vip',{})
        self.assertEqual(value['code'],2002); self.assertIsNone(data)

    def test_period_identity(self):
        with self.assertRaisesRegex(ValueError,'identity_or_period'):
            check_page(self.response(rows=[['600900.SH','20251231','1']]),'secret','income_vip',{'period':'20241231'})

    def test_requested_report_type_is_checked(self):
        with self.assertRaisesRegex(ValueError,'report_type'):
            check_page(self.response(rows=[['600900.SH','20251231','1']]),'secret','income_vip',{'report_type':'5'})

    def test_preserves_same_day_financial_versions(self):
        _,data=check_page(self.response(rows=[['600900.SH','20251231','1']]*2),'secret','income_vip',{})
        self.assertEqual(len(data['items']),2)

    def test_daily_duplicates_fail(self):
        with self.assertRaisesRegex(ValueError,'duplicate_market_key'):
            check_page(self.response(rows=[['600900.SH','20251231']]*2,fields=['ts_code','trade_date']),
                'secret','daily',{})

    def test_missing_paging_is_not_complete(self):
        with self.assertRaisesRegex(ValueError,'paging'):
            check_page(b'{"code":0,"data":{"fields":["a"],"items":[]}}','secret','income_vip',{})

    def test_wrong_fields_and_width(self):
        with self.assertRaisesRegex(ValueError,'fields_mismatch'):
            check_page(self.response(),'secret','income_vip',{},fields='a,b')
        with self.assertRaisesRegex(ValueError,'row_width'):
            check_page(self.response(rows=[['600900.SH']]),'secret','income_vip',{})

    def test_cap_requires_observing_another_offset_even_false_flag(self):
        self.assertTrue(page_continues({'items':[[1]]*5,'has_more':False},5))
        self.assertFalse(page_continues({'items':[],'has_more':False},5))

    def test_more_flag_requires_next_page_below_cap(self):
        self.assertTrue(page_continues({'items':[[1]],'has_more':True},5))
        with self.assertRaisesRegex(ValueError,'empty_page_claims_more'):
            page_continues({'items':[],'has_more':True},5)

    def test_fixed_periods_and_stable_plan_identity(self):
        self.assertEqual(len(quarters()),55)
        self.assertEqual(quarters()[0],'20130331'); self.assertEqual(quarters()[-1],'20260930')
        self.assertEqual(specification('daily',{'trade_date':'20260101'}),specification('daily',{'trade_date':'20260101'}))
        self.assertNotEqual(specification('daily',{'trade_date':'20260101'}),specification('daily',{'trade_date':'20260102'}))

    def collector(self, local):
        obj=Collector.__new__(Collector)
        obj.token='FAKE_CREDENTIAL_FOR_TEST_ONLY'; obj.local=Path(local)
        obj.contract={'maximum_retries':5,'maximum_pages_per_job':10}
        obj.sink=Mock();obj.lock=threading.Lock();obj.rate_lock=threading.Lock()
        obj.spacing=60/420;obj.next_request=0.;obj.responses=[];obj.jobs=[];obj.resume={}
        obj.closed_apis=set();obj.fatal=False
        return obj

    def test_transient_network_retry_preserves_only_public_bytes(self):
        with tempfile.TemporaryDirectory() as local:
            obj=self.collector(local);raw=self.response();value=json.loads(raw)
            obj.request=Mock(side_effect=[URLError('timeout'),(raw,value,value['data'])])
            with patch('qount.research.q_div_acquisition.time.sleep'),patch('qount.research.q_div_acquisition.backoff',return_value=0):
                data,item=obj.fetch_page(specification('income_vip',{}),{},0)
            self.assertEqual(item['attempt'],1);self.assertEqual(obj.request.call_count,2)
            self.assertTrue((Path(local)/'transport-errors.jsonl').exists())
            for call in obj.sink.put.call_args_list:
                self.assertNotIn(obj.token.encode(),call.args[1])

    def test_rate_limit_shared_cooldown_and_bounded_retry(self):
        with tempfile.TemporaryDirectory() as local:
            obj=self.collector(local);bad={'code':2002,'msg':'每分钟访问次数超过限制'}
            raw=self.response();good=json.loads(raw)
            obj.request=Mock(side_effect=[(json.dumps(bad).encode(),bad,None),(raw,good,good['data'])])
            with patch('qount.research.q_div_acquisition.time.sleep'),patch('qount.research.q_div_acquisition.backoff',return_value=15):
                obj.fetch_page(specification('income_vip',{}),{},0)
            self.assertEqual(obj.spacing,60/210);self.assertGreater(obj.next_request,0)
            self.assertEqual(len(obj.responses),2)

    def test_authentication_and_permission_errors_never_retry(self):
        for code,message in ((40101,'token invalid'),(2002,'权限不足')):
            with self.subTest(code=code),tempfile.TemporaryDirectory() as local:
                obj=self.collector(local);bad={'code':code,'msg':message}
                obj.request=Mock(return_value=(json.dumps(bad).encode(),bad,None))
                with self.assertRaisesRegex(ValueError,'provider_error'):
                    obj.fetch_page(specification('income_vip',{}),{},0)
                self.assertEqual(obj.request.call_count,1)
                self.assertIn('income_vip',obj.closed_apis)
                self.assertEqual(obj.fatal,code==40101)

    def test_storage_failure_stops_before_further_requests(self):
        with tempfile.TemporaryDirectory() as local:
            obj=self.collector(local);raw=self.response();good=json.loads(raw)
            obj.request=Mock(return_value=(raw,good,good['data']))
            obj.sink.put.side_effect=BrokenPipeError('broken')
            with self.assertRaisesRegex(RuntimeError,'public_sink_failed'):
                obj.fetch_page(specification('income_vip',{}),{},0)
            self.assertTrue(obj.fatal);self.assertEqual(obj.request.call_count,1)

    def test_ignored_offset_cannot_be_declared_complete(self):
        with tempfile.TemporaryDirectory() as local:
            obj=self.collector(local)
            data={'fields':['ts_code'],'items':[['600900.SH']],'has_more':True}
            obj.fetch_page=Mock(return_value=(data,{'rows':1}))
            result,_=obj.job(specification('income_vip',{},size=1))
            self.assertEqual(result['status'],'failed_or_withheld')
            self.assertIn('offset_ignored',result['error'])

    def test_same_code_without_rate_message_is_not_retried(self):
        self.assertTrue(retryable_provider(2002,'每分钟最多500次'))
        self.assertFalse(retryable_provider(2002,'没有访问权限'))
        self.assertFalse(retryable_provider(40101,'rate limit'))


if __name__=='__main__':
    unittest.main()
