import unittest
from unittest.mock import patch
from qount.research.q_div_data_audit import inspect_job,select_jobs


class DataAuditTests(unittest.TestCase):
    def test_partition_cannot_silently_drop_unplanned_or_duplicate_ids(self):
        plan={'one':{'api_name':'daily'},'two':{'api_name':'daily_basic'}}
        self.assertEqual(select_jobs(plan,['two']),{'two':plan['two']})
        for selected in (['other'],['one','one'],[],['one',None]):
            with self.assertRaises(ValueError):select_jobs(plan,selected)

    def sample(self,counts=(2,1),flags=(True,False),offsets=(0,2)):
        job={'api_name':'income_vip','params':{'period':'20251231','report_type':'1'},'page_size':2,
             'paged':True,'pages':len(counts),'rows':sum(counts),'fields':''}
        receipts=[{'api_name':'income_vip','code':0,'params':{**job['params'],'limit':2,'offset':o},'rows':n}
                  for n,o in zip(counts,offsets,strict=True)]
        data=[{'fields':['ts_code','end_date','report_type'],'items':[[f'600{i}{k}.SH','20251231','1'] for k in range(n)],'has_more':more}
              for i,(n,more) in enumerate(zip(counts,flags,strict=True))]
        return job,receipts,data

    def test_complete_two_page_job(self):
        job,receipts,data=self.sample()
        with patch('qount.research.q_div_data_audit.read_public',side_effect=data):
            self.assertEqual(len(list(inspect_job('/mnt/e/test',job,receipts))),2)

    def test_cap_false_flag_still_needs_terminal_page(self):
        job,receipts,data=self.sample(counts=(2,),flags=(False,),offsets=(0,))
        with patch('qount.research.q_div_data_audit.read_public',side_effect=data),self.assertRaisesRegex(ValueError,'terminal_page'):
            list(inspect_job('/mnt/e/test',job,receipts))

    def test_missing_offset_is_detected(self):
        job,receipts,data=self.sample(offsets=(0,4))
        with patch('qount.research.q_div_data_audit.read_public',side_effect=data),self.assertRaisesRegex(ValueError,'page_gap'):
            list(inspect_job('/mnt/e/test',job,receipts))

    def test_duplicate_page_is_detected(self):
        job,receipts,data=self.sample(counts=(2,2),flags=(True,False))
        with patch('qount.research.q_div_data_audit.read_public',side_effect=[data[0],data[0]]),self.assertRaisesRegex(ValueError,'repeated_page'):
            list(inspect_job('/mnt/e/test',job,receipts))

    def test_source_period_mismatch_is_detected(self):
        job,receipts,data=self.sample()
        data[0]['items'][0][1]='20241231'
        with patch('qount.research.q_div_data_audit.read_public',side_effect=data),self.assertRaisesRegex(ValueError,'row_identity'):
            list(inspect_job('/mnt/e/test',job,receipts))

    def test_monthly_ST_response_must_be_within_requested_dates(self):
        job={'api_name':'stock_st','params':{'start_date':'20250101','end_date':'20250131'},
             'page_size':1000,'paged':True,'pages':1,'rows':1,'fields':''}
        receipts=[{'api_name':'stock_st','code':0,'params':{**job['params'],'limit':1000,'offset':0},'rows':1}]
        data={'fields':['ts_code','trade_date'],'items':[['600001.SH','20250201']],'has_more':False}
        with patch('qount.research.q_div_data_audit.read_public',return_value=data),self.assertRaisesRegex(ValueError,'source_date_range'):
            list(inspect_job('/mnt/e/test',job,receipts))


if __name__=='__main__':unittest.main()
