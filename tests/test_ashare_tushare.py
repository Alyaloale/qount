import json
import unittest
from qount.research.ashare_tushare import NoRedirect, validate_response


class TushareSourceTests(unittest.TestCase):
    def check(self, data=None, api='adj_factor', params=None, fields='ts_code,trade_date,adj_factor', secret='fakecredential', code=0):
        if data is None:data={'fields':fields.split(','),'items':[['000998.SZ','20180828',11.107]],'has_more':False}
        return validate_response(json.dumps({'code':code,'data':data}).encode(),secret=secret,api=api,
            params=params or {'ts_code':'000998.SZ','start_date':'20180827','end_date':'20180828'},fields=fields)
    def test_valid_typed_public_response(self):self.assertEqual(self.check()['rows'],1)
    def test_empty_result_preserved_not_filled(self):
        self.assertEqual(self.check({'fields':['ts_code','trade_date','adj_factor'],'items':[],'has_more':False})['rows'],0)
    def test_credential_in_response_refuses_export(self):
        with self.assertRaisesRegex(ValueError,'contains_credential'):self.check(secret='000998.SZ')
    def test_provider_error(self):
        with self.assertRaisesRegex(ValueError,'provider_error'):self.check(code=2002)
    def test_has_more_rejected(self):
        with self.assertRaisesRegex(ValueError,'paging'):self.check({'fields':['ts_code','trade_date','adj_factor'],'items':[],'has_more':True})
    def test_missing_has_more_rejected(self):
        with self.assertRaisesRegex(ValueError,'paging'):self.check({'fields':['ts_code','trade_date','adj_factor'],'items':[]})
    def test_schema_mismatch(self):
        with self.assertRaisesRegex(ValueError,'schema'):self.check({'fields':['wrong'],'items':[],'has_more':False})
    def test_row_width(self):
        with self.assertRaisesRegex(ValueError,'width'):self.check({'fields':['ts_code','trade_date','adj_factor'],'items':[['000998.SZ']],'has_more':False})
    def test_wrong_security(self):
        with self.assertRaisesRegex(ValueError,'identity'):self.check(params={'ts_code':'000001.SZ','start_date':'20180827','end_date':'20180828'})
    def test_outside_requested_dates(self):
        with self.assertRaisesRegex(ValueError,'range'):self.check(params={'ts_code':'000998.SZ','start_date':'20180829','end_date':'20180830'})
    def test_duplicate_date(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):self.check({'fields':['ts_code','trade_date','adj_factor'],'items':[['000998.SZ','20180828',1]]*2,'has_more':False})
    def test_daily_documented_limit_rejected(self):
        from datetime import date,timedelta
        rows=[['000998.SZ',(date(2000,1,1)+timedelta(days=i)).strftime('%Y%m%d'),1] for i in range(6000)]
        with self.assertRaisesRegex(ValueError,'documented_limit'):
            self.check({'fields':['ts_code','trade_date','adj_factor'],'items':rows,'has_more':False},api='daily',params={'ts_code':'000998.SZ','start_date':'20000101','end_date':'20300101'})
    def test_credential_redirect_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'redirect_refused'):NoRedirect().redirect_request(None,None,302,'',None,'https://other.invalid')


if __name__=='__main__':unittest.main()
