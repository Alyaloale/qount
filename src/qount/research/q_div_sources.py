"""Read immutable paginated P1 inputs, including hash-bound inherited shards."""
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import sys

from qount.research.q_div_data_audit import inspect_job


def group_responses(responses):
    result=defaultdict(list)
    for receipt in responses:
        result[receipt['job_id']].append(receipt)
    return result


def resolve_job(job,root,receipts,inherited):
    if job['status']=='completed':
        return root,job,receipts.get(job['id'],[])
    if job['status']!='reused':
        raise ValueError('requested_input_unavailable:'+job['id'])
    source_root,jobs,source_receipts=inherited[job['source_root']]
    prior=jobs[job['id']]
    if prior['status']!='completed' or any(prior.get(k)!=job.get(k) for k in
            ('api_name','params','fields','page_size','paged','rows','pages')):
        raise ValueError('inherited_shard_mismatch')
    return source_root,prior,source_receipts.get(job['id'],[])


def validate_repair(original,replacement):
    if (original['status']!='failed_or_withheld' or replacement['status']!='completed'
            or any(original.get(k)!=replacement.get(k) for k in
                ('id','api_name','params','fields','page_size','paged'))):
        raise ValueError('repair_shard_identity_mismatch')


class PublicHistorySources:
    """Streaming raw public rows; availability is distinct from PIT eligibility."""
    def __init__(self,root,*,jobs_name='jobs.json',index_name='responses.json',repair_roots=()):
        self.root=Path(root).resolve()
        if (sys.platform!='linux' or not os.path.ismount('/mnt/e') or
                not self.root.is_relative_to('/mnt/e/qount_data/qount/datasets/equity_selection')):
            raise ValueError('public_history_requires_WSL_E')
        self.contract=json.loads((self.root/'contract.json').read_text())
        self.jobs=json.loads((self.root/jobs_name).read_text())
        if len({j['id'] for j in self.jobs})!=len(self.jobs):
            raise ValueError('duplicate_job_inventory')
        self.receipts=group_responses(json.loads((self.root/index_name).read_text()))
        self.inherited={}
        self.manifest={}
        self.repairs={}
        for source in self.contract.get('reuse_sources',[]):
            path=Path(source['root'].replace('E:/','/mnt/e/')).resolve()
            if not path.is_relative_to('/mnt/e/qount_data/qount/datasets/equity_selection'):
                raise ValueError('inherited_root_outside_E')
            prior=json.loads((path/'jobs.json').read_text())
            if len({j['id'] for j in prior})!=len(prior):
                raise ValueError('duplicate_inherited_jobs')
            receipts=group_responses(json.loads((path/'responses.json').read_text()))
            self.inherited[source['root']]=(path,{j['id']:j for j in prior},receipts)
            for name in ('jobs.json','responses.json','contract.json'):
                self.manifest[str(path/name)]=hashlib.sha256((path/name).read_bytes()).hexdigest()
        for name in ('contract.json','seed.json',jobs_name,index_name):
            self.manifest[str(self.root/name)]=hashlib.sha256((self.root/name).read_bytes()).hexdigest()
        original={j['id']:j for j in self.jobs}
        for repair_root in repair_roots:
            reader=PublicHistorySources(repair_root)
            if reader.manifest[str(reader.root/'contract.json')]!=self.manifest[str(self.root/'contract.json')]:
                raise ValueError('repair_contract_mismatch')
            origin_path=reader.root/'repair-origin.json';origin=json.loads(origin_path.read_text())
            if (origin['inventory_sha256']!=self.manifest[str(self.root/jobs_name)]
                    or origin['seed_sha256']!=self.manifest[str(self.root/'seed.json')]
                    or set(origin['repair_job_ids'])!={j['id'] for j in reader.jobs}):
                raise ValueError('repair_origin_mismatch')
            reader.manifest[str(origin_path)]=hashlib.sha256(origin_path.read_bytes()).hexdigest()
            for replacement in reader.jobs:
                if replacement['id'] in self.repairs:
                    raise ValueError('duplicate_repair_shard')
                validate_repair(original[replacement['id']],replacement)
                self.repairs[replacement['id']]=(reader,replacement)
            self.manifest.update(reader.manifest)

    def pages(self,api,**params):
        matches=[j for j in self.jobs if j['api_name']==api and all(j['params'].get(k)==v for k,v in params.items())]
        if not matches:
            raise ValueError('requested_input_not_collected:'+api)
        for job in sorted(matches,key=lambda j:j['id']):
            reader,replacement=self.repairs.get(job['id'],(self,job))
            root,original,receipts=resolve_job(replacement,reader.root,reader.receipts,reader.inherited)
            for data in inspect_job(root,original,receipts):
                yield data
            for receipt in receipts:
                if receipt['code']==0:
                    self.manifest[str(root/receipt['file'])]=receipt['file_sha256']

    def financial_sources(self,*,symbols=None,periods=None,report_types=('1',)):
        wanted=None if symbols is None else set(symbols)
        for api in ('income','cashflow','balancesheet'):
            vendor=api+'_vip'
            for report_type in report_types:
                selected_periods=periods if periods is not None else sorted({j['params']['period'] for j in self.jobs
                    if j['api_name']==vendor and j['params'].get('report_type')==report_type})
                for period in selected_periods:
                    for data in self.pages(vendor,period=period,report_type=report_type):
                        fields=data['fields'];index=fields.index('ts_code')
                        yield api,[dict(zip(fields,row,strict=True)) for row in data['items']
                            if wanted is None or row[index] in wanted]
