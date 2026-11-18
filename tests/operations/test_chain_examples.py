"""Paired saved examples must agree across native module results and global execution."""
import asyncio
import copy
import json
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient
from metaforge.operations.baselines import dataset_root, make_config, list_baselines
from metaforge.operations.chain_sources import assembly_source, assembly_catalog, supply_source, route_source
from metaforge.operations.chain import build_chain
from metaforge.operations.cases import rebase_case
from metaforge.operations.distributed import load_production_sources
from metaforge.operations.sources import production_plan, select_production_jobs
from metaforge.operations.runtime import advance
from metaforge.operations.models import new_state
from metaforge.operations.coordinator import metrics
from metaforge.operations.api import create_router
from metaforge.operations.service import OperationsService
from metaforge.operations.store import MemoryStore
from .test_source_alignment import Collection

NOW=1800000000.0
IDS=['chain-demo-normal','chain-demo-supply','chain-demo-transport']

def doc(key):
 d=json.loads((dataset_root(key)/'production_result.json').read_text(encoding='utf-8')); d['_id']=ObjectId(d['id']); return d

async def loader(raw,start):
 d=next(doc(key) for key in IDS if doc(key)['id']==raw['plan_id'])
 offset=float(raw.get('source_zero_offset_hours') or 0)
 p=production_plan(d,d['machines'],[],start-offset*3600,solver=raw['solver_id'],time_unit=raw['time_unit'])
 p=select_production_jobs(p,raw.get('job_indices'),offset)
 p['source_manifest'][0]['origin_at']=start-offset*3600; p['start_at']=start
 return p

def configured(key,start=NOW):
 c=asyncio.run(make_config(key,loader,start))['config']; c['confirmed']=True; return c

def build(c):
 root=dataset_root(c['source_dataset'])
 return build_chain(asyncio.run(load_production_sources(c,loader,c['start_at'])),c,supply_source(root),assembly_source(c['assembly_id'],None),route_source(c['route_id'],root))

@pytest.mark.parametrize('key',IDS)
def test_saved_examples_complete_chain_and_preserve_exact_module_outputs(key):
 c=configured(key); p=build(c)
 assert c['assembly_mode']=='saved' and c['assembly_id']=='example:'+key
 assert len(p['tasks'])==66 and p['business_validation']['passed'] and p['time_validation']['passed']
 assert len(p['source_schedule'])==45 and p['chain_summary']['assembly_changes']==[]
 original={r['task_id']:r for r in p['source_schedule']}
 for r in p['schedule']:
  if r['task_id'] in original: assert all(r[k]==v for k,v in original[r['task_id']].items())
 source=assembly_source(c['assembly_id'],None)
 assert source['algorithm']=='原工艺约束规则排程' and source['mode']=='saved_rule_example'
 assert all(t['source_ref']['mode']=='saved_rule_example' for t in p['tasks'] if t['id'] in original)
 end=max(r['end_at'] for r in p['schedule'])
 final,_=advance(new_state(p,NOW),end+1)
 assert all(t['status']=='completed' for t in final['tasks'].values())
 assert all(q>=-1e-6 for q in final['inventory'].values())
 assert final['inventory']['warehouse|chain:finished']==0
 assert metrics(final,[])['total_delay_seconds']==0
 rebased=rebase_case(p,NOW+3*86400+777)['chain_config']; rebased['confirmed']=True
 shifted=build(rebased)
 for left,right in zip(p['schedule'],shifted['schedule']):
  assert right['start_at']-left['start_at']==pytest.approx(3*86400+777)


def test_cases_change_real_readiness_parameters_and_keep_same_verified_customer_demand():
 normal,late,transport=[configured(k) for k in IDS]
 assert late['inbound_shipments'][2]['ship_at']-normal['inbound_shipments'][2]['ship_at']==5*86400
 assert transport['calendar']['days']==28
 plans=[build(c) for c in [normal,late,transport]]
 finishes=[max(r['end_at'] for r in p['schedule'] if r['task_id'].startswith('chain:unit:')) for p in plans]
 assert finishes[1]>finishes[0] and finishes[2]>finishes[0]
 assert {sum(o['quantity'] for o in p['orders'] if o.get('role')!='component') for p in plans}=={5}


def test_example_results_available_without_qmix_server_and_unknown_paths_rejected():
 rows=[r for r in assembly_catalog(None)['results'] if r.get('case_id')]
 assert {r['case_id'] for r in rows}==set(IDS)
 assert all(r['compatible'] for r in rows)
 with pytest.raises(ValueError): assembly_source('example:../../outside',None)


def test_module_example_api_and_baseline_api_reference_the_same_saved_results_without_activation():
 docs=[doc(k) for k in IDS]
 app=FastAPI(); app.include_router(create_router(OperationsService(MemoryStore(),clock=lambda:NOW),Collection(docs),Collection(docs[0]['machines']),Collection([])))
 with TestClient(app) as client:
  for key in IDS:
   module=client.get('/api/operations-tools/plans/chain/examples/'+key)
   assert module.status_code==200,module.text
   payload=module.json(); assert payload['production_plan_id']==doc(key)['id']
   baseline=client.post('/api/operations-tools/plans/chain/baseline',json={'case_id':key,'start_at':NOW+900})
   assert baseline.status_code==200,baseline.text
   c=baseline.json()['config']; assert not c['confirmed']
   assert payload['assembly']['id']==c['assembly_id']
   c['confirmed']=True
   preview=client.post('/api/operations-tools/plans/chain/preview',json=c)
   assert preview.status_code==200,preview.text
   assert preview.json()['can_activate']
  assert client.get('/api/operations-tools/current').json()['instance'] is None
