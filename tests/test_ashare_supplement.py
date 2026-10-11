import json
import tempfile
import unittest
from pathlib import Path
from qount.research.ashare_supplement import (RAW_FIELDS, FACTOR_FIELDS, acquire, collect_pages,
    factor_profile, raw_profile, select_missing_retired)

PREFIXES = {'SH': ['600','601','603','605'], 'SZ':['000','001','002','003']}

def basic(rows):
    return {'fields':['code','code_name','ipoDate','outDate','type','status'], 'rows':rows}

def quote(day='2020-01-02', code='sh.600005', **changes):
    r = dict(zip(RAW_FIELDS, [day,code,'10','11','9','10','10','100','1000','1','0']))
    r.update(changes)
    return [r[k] for k in RAW_FIELDS]

class Result:
    def __init__(self, pages, fields=None, mode=None):
        self.pages=pages;self.fields=fields or RAW_FIELDS;self.error_code='0';self.cur_page_num='1'
        self.data=pages[0];self.cur_row_num=0;self.mode=mode
    def next(self):
        if self.mode=='masked_empty_response':return False
        if self.mode=='provider_error':self.error_code='999';return False
        i=int(self.cur_page_num);self.cur_page_num=str(i+1);self.data=self.pages[i];self.cur_row_num=0
        return bool(self.data)

class AshareSupplementTests(unittest.TestCase):
    def test_selection_includes_retired_missing_not_current_pool(self):
        rows=[['sh.600005','x','1999-01-01','2017-02-14','1','0'],
              ['sh.600068','x','1999-01-01','2021-09-13','1','0'],
              ['sh.600000','x','1999-01-01','','1','1'],
              ['sz.300001','x','2009-01-01','2020-01-02','1','0'],
              ['sh.600070','x','1999-01-01','2026-10-01','1','0']]
        r=select_missing_retired(basic(rows),{'600068.SH'},PREFIXES,'2015-01-01','2026-09-30')
        self.assertEqual([x['code'] for x in r],['sh.600005'])
        self.assertFalse(r[0]['historical_board_certified'])
    def test_duplicate_master_identity_rejected(self):
        row=['sh.600005','x','1999-01-01','2017-02-14','1','0']
        with self.assertRaisesRegex(ValueError,'duplicate'):
            select_missing_retired(basic([row,row]),set(),PREFIXES,'2015-01-01','2026-09-30')
    def test_metadata_width_rejected(self):
        with self.assertRaises(ValueError):select_missing_retired(basic([['x']]),set(),PREFIXES,'2015-01-01','2026-09-30')
    def test_complete_short_page_does_not_request_next(self):
        saved=[];r=collect_pages(Result([[quote()]]),RAW_FIELDS,lambda n,p:saved.append(p))
        self.assertEqual(len(saved),1);self.assertEqual(len(r['rows']),1)
    def test_complete_full_page_requires_and_keeps_empty_terminal_page(self):
        saved=[];r=collect_pages(Result([[quote(),quote()],[]]),RAW_FIELDS,lambda n,p:saved.append(p),2)
        self.assertEqual([len(p['rows']) for p in saved],[2,0]);self.assertEqual(len(r['rows']),2)
    def test_multiple_pages_preserve_exact_records(self):
        r=collect_pages(Result([[quote(),quote()],[quote()]]),RAW_FIELDS,lambda n,p:None,2)
        self.assertEqual(len(r['rows']),3);self.assertTrue(r['protocol_complete'])
    def test_masked_empty_protocol_failure_not_complete(self):
        with self.assertRaisesRegex(ValueError,'pagination_failed'):
            collect_pages(Result([[quote(),quote()]],mode='masked_empty_response'),RAW_FIELDS,lambda n,p:None,2)
    def test_provider_error_during_pagination_rejected(self):
        with self.assertRaises(ValueError):collect_pages(Result([[quote(),quote()]],mode='provider_error'),RAW_FIELDS,lambda n,p:None,2)
    def test_unexpected_unpaged_collection_rejected(self):
        with self.assertRaisesRegex(ValueError,'unpaged'):collect_pages(Result([[quote()]*3]),RAW_FIELDS,lambda n,p:None,2)
    def test_field_drift_rejected_before_accepting_rows(self):
        with self.assertRaises(ValueError):collect_pages(Result([[quote()]],fields=['wrong']),RAW_FIELDS,lambda n,p:None)
    def test_halt_st_and_missing_values_preserved(self):
        payload={'rows':[quote(tradestatus='0',isST='1',volume='',amount='')]}
        r=raw_profile(payload,'sh.600005','2013-01-01','2026-09-30')
        self.assertEqual(r['counts']['rows'],1);self.assertEqual(r['counts']['halted_rows'],1)
        self.assertEqual(r['counts']['ST_rows'],1);self.assertEqual(r['counts']['missing_activity_rows'],1)
        self.assertFalse(r['terminal_recovery_or_open_fill_certified'])
        self.assertEqual(payload['rows'][0][7],'')
    def test_identity_and_duplicate_date_rejected(self):
        for rows in [[quote(code='sh.600006')],[quote(),quote()]]:
            with self.assertRaises(ValueError):raw_profile({'rows':rows},'sh.600005','2013-01-01','2026-09-30')
    def test_outside_frozen_window_rejected(self):
        with self.assertRaises(ValueError):raw_profile({'rows':[quote('2026-10-01')]},'sh.600005','2013-01-01','2026-09-30')
    def test_empty_factor_set_remains_empty(self):
        r=factor_profile({'rows':[]},'sh.600005','1990-12-19','2026-09-30')
        self.assertEqual(r['factor_events'],0);self.assertTrue(r['empty_event_set_not_imputed'])
    def test_nonfinite_factor_rejected(self):
        with self.assertRaises(ValueError):factor_profile({'rows':[['sh.600005','2020-01-02','nan','2','2']]},'sh.600005','1990-12-19','2026-09-30')
    def test_factor_events_order_and_identity_rejected(self):
        row=['sh.600005','2020-01-02','1','2','2']
        with self.assertRaises(ValueError):factor_profile({'rows':[row,row]},'sh.600005','1990-12-19','2026-09-30')
    def test_mac_guard_precedes_sdk_or_network_import(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root);contract=path/'c.json'
            contract.write_text(json.dumps({'phase':'retired_source_supplement','research_only':True,'orders_authorized':False,'returns_produced':False}))
            with self.assertRaisesRegex(ValueError,'requires_wsl'):
                acquire(contract_path=contract,out=path/'new',sdk_root=path/'missing-sdk')
            self.assertFalse((path/'new').exists())

if __name__=='__main__':unittest.main()
