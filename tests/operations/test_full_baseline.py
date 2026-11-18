"""A complete native-derived case must execute, reject broken handoffs, and replay exactly."""
import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient
from contextlib import asynccontextmanager

from metaforge.operations.baselines import make_config, dataset_root, list_baselines
from metaforge.operations.chain import build_chain
from metaforge.operations.chain_sources import route_source, supply_source
from metaforge.operations.sources import production_plan, select_production_jobs, ROOT
from metaforge.operations.distributed import load_production_sources
from metaforge.operations.cases import rebase_case
from metaforge.operations.coordinator import metrics, schedule
from metaforge.operations.models import new_state
from metaforge.operations.runtime import advance, apply_event
from metaforge.operations.validator import validate
from metaforge.operations.temporal import temporal_report
from metaforge.operations.api import create_router
from metaforge.operations.service import OperationsService
from metaforge.operations.store import MemoryStore
from .test_source_alignment import Collection

NOW = 1_800_000_000.0

def source():
    d = json.loads((ROOT / 'data/operations/standard/production_source.json').read_text(encoding='utf-8'))
    d['_id'] = ObjectId(d['id'])
    return d

async def loader(raw, start):
    d = source(); offset = float(raw.get('source_zero_offset_hours') or 0)
    p = production_plan(d, d['machines'], [], start-offset*3600, solver=raw.get('solver_id'), time_unit=raw.get('time_unit','hours'))
    p = select_production_jobs(p, raw.get('job_indices'), offset)
    p['source_manifest'][0]['origin_at'] = start-offset*3600; p['start_at'] = start
    return p

def configured(start=NOW):
    c = asyncio.run(make_config('fridge-chain-v1', loader, start))['config']; c['confirmed'] = True
    return c

def build(c):
    native = asyncio.run(load_production_sources(c,loader,c['start_at']))
    directory = dataset_root(c['source_dataset'])
    return build_chain(native,c,supply_source(directory),logistics=route_source(c['route_id'],directory))


def test_full_baseline_has_native_factory_scopes_independent_bom_procurement_and_verified_route():
    c = configured(); p = build(c)
    assert p['business_validation']['passed'] and p['time_validation']['passed']
    assert len(p['tasks']) == 66 and len(p['business_validation']['inbound_tasks']) == 8
    assert len(c['assembly_bom']['lines']) == 12 and len(c['procurement_orders']) == 10
    assert len(p['production_sources']) == 2
    machines = {r['id']:r['factory_id'] for r in p['resources'] if r['kind']=='production'}
    assert len(machines)==7
    assert {m for m,f in machines.items() if f=='CASE-FACTORY-A'} == {'production:machine:2','production:machine:4','production:machine:5'}
    assert set(p['coverage'].values()) == {'bound'}
    for manifest, selection in zip(p['production_sources'],c['production_sources']):
        assert manifest['job_indices']==selection['job_indices']
    original = source()
    for t in p['tasks']:
        if t['kind']!='production': continue
        ref=t['source_ref']; j=original['jobs'][ref['job_index']]
        native_row=next(r for r in original['schedule_results']['q']['gantt_data'] if r['job_name']==j['name'] and r['operation_name']==ref['operation_name'])
        row=next(r for r in p['schedule'] if r['task_id']==t['id'])
        assert row['end_at']-row['start_at']==(native_row['end']-native_row['start'])*3600


def test_full_case_runs_to_all_five_deliveries_with_no_negative_or_teleported_stock():
    p=build(configured()); end=max(r['end_at'] for r in p['schedule'])
    final,events=advance(new_state(p,NOW),end+1)
    assert final['status']=='idle' and all(t['status']=='completed' for t in final['tasks'].values())
    assert len([e for e in events if e['type']=='task_completed'])==66
    assert all(q>=-1e-6 for q in final['inventory'].values())
    assert final['inventory']['warehouse|chain:finished']==0
    result=metrics(final,[])
    assert result['unknown_commitments']==0 and result['unknown_orders']==0 and result['total_delay_seconds']==0
    assert sum(o['quantity']for o in p['orders']if o.get('role')!='component')==5
    incoming=next(t for t in p['tasks']if t['kind']=='transport'and 'CASE-FACTORY-A' in t['id'])
    slot=next(s for s in p['schedule']if s['task_id']==incoming['id'])
    partial,_=advance(new_state(p,NOW),slot['end_at']-1)
    for line in incoming['outputs']: assert partial['inventory'].get(line['location']+'|'+line['material_id'],0)==0


@pytest.mark.parametrize('change,reason', [('early_factory','发运不能早于'),('wrong_eta','到货ETA'),('early_loading','固定发运|无可行'),('wrong_product','配送产品')])
def test_broken_inter_stage_contracts_cannot_be_enabled(change,reason):
    c=configured()
    if change=='early_factory':
        t=c['inbound_shipments'][0]; delta=t['ship_at']-NOW; t['ship_at']=NOW; t['arrival_at']-=delta
    if change=='wrong_eta': c['additional_supplies'][0]['available_at']-=60
    if change=='early_loading':
        day=datetime.fromtimestamp(NOW,timezone(timedelta(hours=8))).replace(hour=8,minute=0,second=0,microsecond=0)
        c.update(delivery_origin_at=day.timestamp(),delivery_date=day.date().isoformat())
    if change=='wrong_product': c['dispatch_product_id']='DIFFERENT'
    with pytest.raises(ValueError,match=reason): build(c)


def test_replay_and_rebuild_keep_exact_cross_stage_offsets_even_when_crossing_midnight():
    p=build(configured()); start=NOW+3*86400+7*3600+37.5
    replay=rebase_case(p,start); c=copy.deepcopy(replay['chain_config']);c['confirmed']=True
    rebuilt=build(c)
    assert rebuilt['chain_source_versions']['production']==p['chain_source_versions']['production']
    old={s['task_id']:s for s in p['schedule']}; delta=start-NOW
    for row in rebuilt['schedule']:
        assert row['start_at']==pytest.approx(old[row['task_id']]['start_at']+delta)
        assert row['end_at']==pytest.approx(old[row['task_id']]['end_at']+delta)
    for row in replay['schedule']:
        for field in ['arrive_at','service_start_at']:
            if field in old[row['task_id']]: assert row[field]==pytest.approx(old[row['task_id']][field]+delta)
    assert temporal_report(replay)['passed']
    assert validate(new_state(replay,start),{'schedule':replay['schedule'],'routes':replay['routes']},start)['passed']


def test_factory_slices_do_not_duplicate_orders_or_shared_physical_machines():
    c=configured();c['production_sources'][1]['job_indices']=[8]
    with pytest.raises(ValueError,match='同一生产计划|重复引用'): asyncio.run(load_production_sources(c,loader,NOW))
    c=configured();c['production_sources'][1]['job_indices']=[9];c['production_sources'][1]['source_zero_offset_hours']=30
    # Factory A uses 2/4/5, job9 uses 0/1/6/7, so still a legal physical split.
    assert len(asyncio.run(load_production_sources(c,loader,NOW))['orders'])==2
    c['production_sources'][1]['job_indices']=[0];c['production_sources'][1]['source_zero_offset_hours']=12
    with pytest.raises(ValueError,match='不能同时属于'): asyncio.run(load_production_sources(c,loader,NOW))


def test_exact_time_origin_cannot_disagree_with_the_selected_delivery_date():
    c=configured();c['delivery_origin_at']+=86400
    with pytest.raises(ValueError,match='配送日期与配送时间原点不一致'): build(c)


def test_case_does_not_auto_repair_a_fault_or_release_downstream_parts():
    p=build(configured()); state,_=advance(new_state(p,NOW),NOW+60)
    rid='production:machine:2'
    state,_=apply_event(state,{'type':'resource_unavailable','target_id':rid,'data':{'expected_recovery_at':NOW+1260}},NOW+60)
    state,_=advance(state,NOW+1300)
    assert not state['resources'][rid]['available']
    assert any(t['status']=='paused'and t['resource_id']==rid for t in state['tasks'].values())
    with pytest.raises(ValueError,match='缺少有效恢复估计'):
        schedule(state,NOW+1300,'original')
    state,_=apply_event(state,{'type':'resource_recovered','target_id':rid,'data':{}},NOW+1300)
    candidate=schedule(state,NOW+1300,'original')
    assert validate(state,candidate,NOW+1300)['passed']
    state['schedule']=candidate['schedule'];state['routes']=candidate['routes']
    final,_=advance(state,max(s['end_at']for s in candidate['schedule'])+1)
    assert final['status']=='idle'


def test_baseline_api_uses_regular_preview_and_returns_editable_configuration():
    d=source();clock=[NOW];store=MemoryStore();service=OperationsService(store,clock=lambda:clock[0],tick_seconds=.01)
    @asynccontextmanager
    async def lifespan(app):
        await service.start();yield;await service.stop()
    app=FastAPI(lifespan=lifespan);app.include_router(create_router(service,Collection([d]),Collection(d['machines']),Collection([])))
    with TestClient(app) as client:
        result=client.post('/api/operations-tools/plans/chain/baseline',json={'case_id':'fridge-chain-v1','start_at':NOW+900})
        assert result.status_code==200,result.text
        c=result.json()['config'];assert not c['confirmed']
        assert client.post('/api/operations-tools/plans/chain/preview',json=c).status_code==422
        c['confirmed']=True
        preview=client.post('/api/operations-tools/plans/chain/preview',json=c)
        assert preview.status_code==200,preview.text
        assert preview.json()['summary']['time_validation']['passed']
        assert client.get('/api/operations-tools/current').json()['instance'] is None
        rebased=client.post('/api/operations-tools/plans/chain/rebase',json={'config':c,'start_at':NOW+1800})
        assert rebased.status_code==200 and rebased.json()['config']['start_at']==NOW+1800
        assert not rebased.json()['config']['confirmed']
        assert client.get('/api/operations-tools/plans/chain/sources?dataset=../../').status_code==422
        activated=client.post('/api/operations-tools/plans/activate',json={'source':'chain','preview_id':preview.json()['preview_id']})
        assert activated.status_code==200,activated.text
        old=client.get('/api/operations-tools/current').json()['instance']
        clock[0]=NOW+1000
        reload=client.post('/api/operations-tools/cases/reload',json={'run_id':old['run_id'],'confirmed':True})
        assert reload.status_code==200,reload.text
        new=client.get('/api/operations-tools/current').json()['instance']
        assert new['run_id']!=old['run_id'] and new['plan']['business_validation']['passed'] and new['plan']['time_validation']['passed']
        restored=copy.deepcopy(new['plan']['chain_config']);restored['confirmed']=True
        rebuilt=client.post('/api/operations-tools/plans/chain/preview',json=restored)
        assert rebuilt.status_code==200,rebuilt.text
        assert rebuilt.json()['can_activate'] and rebuilt.json()['summary']['time_validation']['passed']


def test_solver_proof_includes_case_road_matrix_and_engine_artifacts(tmp_path):
    from zhenjie.result_versions import status
    import shutil
    directory=dataset_root('fridge-chain-v1')/'zhenjie'
    for name in ['customers_day1.csv','operations_result_manifest.json','road_matrices.json','solver_source.py','best_stage2_balanced_vehicle_route_sequence.csv','best_stage2_balanced_vehicle_timeline.csv']:
        shutil.copyfile(directory/name,tmp_path/name)
    assert status(tmp_path)['verified']
    (tmp_path/'road_matrices.json').write_text('{}',encoding='utf-8')
    assert not status(tmp_path)['verified']


def test_reading_two_factory_scopes_cannot_mix_revisions_of_the_same_source():
    c=configured(); count=[0]
    async def changed_loader(raw,start):
        native=await loader(raw,start);count[0]+=1
        if count[0]==2: native['source_manifest'][0]['source_sha256']='updated-during-read'
        return native
    with pytest.raises(ValueError,match='读取期间已变化'):
        asyncio.run(load_production_sources(c,changed_loader,NOW))
