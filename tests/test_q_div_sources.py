import unittest
from qount.research.q_div_sources import PublicHistorySources,group_responses,resolve_job,validate_repair


class PublicSourceTests(unittest.TestCase):
    def test_repair_cannot_override_success_or_a_different_request(self):
        failed=self.spec('failed_or_withheld');replacement=self.spec()
        validate_repair(failed,replacement)
        for original,new in [(replacement,replacement),(failed,{**replacement,'params':{'period':'20251231'}})]:
            with self.assertRaisesRegex(ValueError,'repair_shard_identity'):
                validate_repair(original,new)

    def spec(self,status='completed'):
        return {'id':'income-shard','api_name':'income_vip','params':{'period':'20260630','report_type':'1'},
            'fields':'','page_size':5000,'paged':True,'pages':1,'rows':1,'status':status}

    def test_reuse_must_resolve_to_matching_completed_source(self):
        old=self.spec();job={**old,'status':'reused','source_root':'E:/prior'}
        receipts=group_responses([{'job_id':old['id'],'rows':1}])
        sources={'E:/prior':('/mnt/e/prior',{old['id']:old},receipts)}
        self.assertEqual(resolve_job(job,'current',{},sources)[0],'/mnt/e/prior')
        sources['E:/prior'][1][old['id']]={**old,'rows':2}
        with self.assertRaisesRegex(ValueError,'inherited_shard_mismatch'):
            resolve_job(job,'current',{},sources)

    def test_unavailable_input_is_not_an_empty_dataset(self):
        with self.assertRaisesRegex(ValueError,'unavailable'):
            resolve_job(self.spec('failed_or_withheld'),'current',{}, {})

    def test_financial_rows_preserve_original_fields_and_filter_symbols(self):
        reader=PublicHistorySources.__new__(PublicHistorySources)
        reader.jobs=[{**self.spec(),'api_name':api+'_vip'} for api in ('income','cashflow','balancesheet')]
        calls=[]
        def pages(api,**params):
            calls.append((api,params))
            yield {'fields':['ts_code','end_date','report_type','update_flag'],
                'items':[['600900.SH','20260630','1','0'],['600901.SH','20260630','1','1']]}
        reader.pages=pages
        sources=list(reader.financial_sources(symbols=['600900.SH'],periods=['20260630']))
        self.assertEqual(len(sources),3)
        self.assertEqual(sources[0][1][0]['update_flag'],'0')
        self.assertTrue(all(len(rows)==1 for _,rows in sources))
        self.assertEqual(calls[0][1],{'period':'20260630','report_type':'1'})


if __name__=='__main__':unittest.main()
