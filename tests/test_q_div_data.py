import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.research.q_div_data import bundle


class QDivSourceTests(unittest.TestCase):
    def source(self, root, *, has_more=False, items=None):
        spec={'id':'basic','api_name':'daily_basic','params':{'trade_date':'20260930'},
              'fields':'ts_code,trade_date','role':'test'}
        contract={'requests':[spec]}
        (root/'contract.json').write_text(json.dumps(contract))
        raw=json.dumps({'code':0,'data':{'fields':['ts_code','trade_date'],
                       'items':items if items is not None else [['000333.SZ','20260930']],
                       'has_more':has_more}}).encode()
        (root/'raw.json.gz').write_bytes(gzip.compress(raw))
        acquisition={'status':'completed','completed_requests':1,'credentials_persisted_or_exported':False,
                     'contract_sha256':hashlib.sha256((root/'contract.json').read_bytes()).hexdigest(),
                     'responses':[{**spec,'fields':spec['fields'].split(','),'file':'raw.json.gz','rows':len(json.loads(raw)['data']['items']),
                                   'raw_response_sha256':hashlib.sha256(raw).hexdigest()}]}
        (root/'acquisition.json').write_text(json.dumps(acquisition))

    def test_verified_public_response_and_fingerprints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.source(root)
            with patch('qount.research.q_div_data.DATASETS',root.resolve()):
                rows,fingerprint=bundle(root)
            self.assertEqual(rows[0][1][0]['ts_code'],'000333.SZ')
            self.assertEqual(len(fingerprint['files']),3)

    def test_paging_unknown_wrong_identity_or_truncated_limit_rejected(self):
        cases=[{'has_more':None},{'items':[['000333.SZ','20261009']]},
               {'items':[['000333.SZ','20260930']]*6000}]
        for kwargs in cases:
            with self.subTest(kwargs=list(kwargs)),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);self.source(root,**kwargs)
                with patch('qount.research.q_div_data.DATASETS',root.resolve()),self.assertRaises(ValueError):bundle(root)

    def test_raw_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.source(root)
            (root/'raw.json.gz').write_bytes(gzip.compress(b'{}'))
            with patch('qount.research.q_div_data.DATASETS',root.resolve()),self.assertRaisesRegex(ValueError,'hash_mismatch'):
                bundle(root)

    def test_receipt_schema_is_array_and_request_identity_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.source(root)
            p=root/'acquisition.json';value=json.loads(p.read_text())
            value['responses'][0]['fields']='ts_code,trade_date'
            p.write_text(json.dumps(value))
            with patch('qount.research.q_div_data.DATASETS',root.resolve()),self.assertRaisesRegex(ValueError,'receipt_mismatch'):
                bundle(root)


if __name__=='__main__':unittest.main()
