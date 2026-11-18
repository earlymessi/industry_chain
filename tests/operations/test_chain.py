import copy
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metaforge.operations.api import create_router
from metaforge.operations.chain import build_chain
from metaforge.operations.chain_sources import route_source, supply_source
from metaforge.operations.coordinator import schedule
from metaforge.operations.models import new_state
from metaforge.operations.plans import normalize_plan
from metaforge.operations.production_sync import NewRunRequired, synchronize
from metaforge.operations.runtime import advance, apply_event
from metaforge.operations.service import OperationsService
from metaforge.operations.sources import ROOT, fingerprint, production_plan
from metaforge.operations.store import MemoryStore
from metaforge.operations.validator import validate
from .test_source_alignment import MACHINES, Collection, tiny_doc

NOW = 1_800_000_000.0


def native(units=2, start=NOW):
    doc = tiny_doc(); doc['jobs'][0]['quantity'] = units
    return normalize_plan(production_plan(doc, MACHINES, [], start, solver='ts', time_unit='minutes'))


def config(plan):
    return {'name': '测试完整批次', 'confirmed': True, 'units': plan['orders'][0]['quantity'],
            'start_at': plan['start_at'], 'production': {'plan_id': plan['source_plan_id'], 'solver_id': 'ts', 'time_unit': 'minutes'},
            'assembly_mode': 'supplement', 'delivery_mode': 'unbound', 'calendar': {'mode': 'continuous', 'days': 7},
            'parts': [{'order_id': plan['orders'][0]['id'], 'produced_quantity': plan['orders'][0]['quantity'], 'per_unit': 1, 'process_id': 0}],
            'purchased': [], 'transfer_minutes': 15, 'post_minutes': 10, 'loading_minutes': 20}


def supplies(stock=100, deliveries=None):
    data = {'catalog': [{'id': 'compressor', 'name': '压缩机', 'workstation': '压缩机安装'}],
            'state': {'materials': {'compressor': {'on_hand': stock}}, 'deliveries': deliveries or [], 'updated_at': NOW}}
    data['version'] = fingerprint(data)
    return data


def delivery_config(c, route, start):
    c.update(delivery_mode='saved', route_id=route['route']['id'], vehicle_capacity=12,
             delivery_date=(datetime.fromtimestamp(start, timezone(timedelta(hours=8))) + timedelta(days=2)).strftime('%Y-%m-%d'))
    return c


def test_chain_preserves_production_and_executes_handover_inventory_once():
    base = native(); c = config(base)
    c['purchased'] = [{'material_id': 'compressor', 'per_unit': 1, 'process_id': 3}]
    plan = build_chain(base, c, supplies())
    rows = {r['task_id']: r for r in plan['schedule']}
    for row in base['schedule']:
        assert all(rows[row['task_id']][key] == row[key] for key in ('start_at', 'end_at', 'resource_id'))
    assert rows['chain:transfer']['start_at'] >= max(r['end_at'] for r in base['schedule'])
    state = new_state(plan, NOW)
    assert validate(state, {'schedule': plan['schedule'], 'routes': []}, NOW)['passed']
    final, _ = advance(state, max(r['end_at'] for r in plan['schedule']) + 10)
    assert final['status'] == 'idle'
    assert final['inventory']['warehouse|chain:finished'] == 2
    assert final['inventory']['assembly|compressor'] == 98
    assert all(p['status'] == 'completed' for p in final['tasks'].values())


def test_batch_quantities_and_calendar_are_explicit_and_not_guessed():
    base = native(); c = config(base)
    c['confirmed'] = False
    with pytest.raises(ValueError, match='确认'):
        build_chain(base, c, supplies())
    c['confirmed'] = True; c['parts'][0]['produced_quantity'] = 1
    with pytest.raises(ValueError, match='数量不符'):
        build_chain(base, c, supplies())
    c = config(base); c['calendar'] = {'mode': 'shift', 'days': 7, 'begin_hour': 0, 'end_hour': 1}
    with pytest.raises(ValueError, match='原生产甘特'):
        build_chain(base, c, supplies())


def test_supplier_arrivals_have_fixed_snapshot_anchor_and_no_double_count():
    base = native(); c = config(base)
    c['purchased'] = [{'material_id': 'compressor', 'per_unit': 1, 'process_id': 3}]
    data = supplies(0, [{'id': 'on-way', 'material_id': 'compressor', 'quantity': 2, 'eta_minutes': 180, 'status': 'on_the_way'},
                        {'id': 'already-arrived', 'material_id': 'compressor', 'quantity': 999, 'status': 'arrived'}])
    plan = build_chain(base, c, data)
    assert len(plan['supplies']) == 1 and plan['supplies'][0]['available_at'] == NOW + 180 * 60
    assert all(s['start_at'] >= NOW + 180 * 60 for s in plan['schedule'] if ':process:3' in s['task_id'])
    assert build_chain(base, c, data)['supplies'] == plan['supplies']
    data['state']['deliveries'][0]['quantity'] = 1
    with pytest.raises(ValueError, match='无可行|缺少'):
        build_chain(base, c, data)
    c['additional_supplies'] = [{'id': 'manual', 'material_id': 'compressor', 'quantity': 1, 'available_at': NOW + 6 * 3600}]
    supplemented = build_chain(base, c, data)
    assert len(supplemented['supplies']) == 2
    assert max(s['start_at'] for s in supplemented['schedule'] if ':process:3' in s['task_id']) >= NOW + 6 * 3600


def test_saved_qmix_is_validated_and_time_adjustments_are_visible():
    base = native(); c = config(base)
    reference = build_chain(base, c, supplies())
    rows = [r for r in reference['schedule'] if r['task_id'].startswith('chain:unit:')]
    origin = min(r['start_at'] for r in rows)
    data = [[(r['start_at'] - origin) / 60, (r['end_at'] - r['start_at']) / 60,
             int(r['resource_id'].split(':')[-1]), int(r['task_id'].split(':')[2])] for r in rows]
    saved = {'id': 'test:1', 'units': 2, 'rows': data, 'version': fingerprint(data)}
    c.update(assembly_mode='saved', assembly_origin_at=NOW, assembly_time_unit='minutes')
    plan = build_chain(base, c, supplies(), saved)
    assert plan['chain_summary']['assembly_changes'] and plan['source_schedule']
    assert plan['time_mapping'][1]['origin_at'] == NOW
    saved['rows'] = data[:-1]
    with pytest.raises(ValueError, match='全部9道'):
        build_chain(base, c, supplies(), saved)


def test_route_dates_and_fixed_departure_do_not_move_to_follow_production():
    base = native(5); source = route_source('Stage2_Balanced:1:0')
    c = delivery_config(config(base), source, NOW)
    plan = build_chain(base, c, supplies(), logistics=source)
    deadline = plan['time_mapping'][-1]['departure_at']
    first = next(t for t in plan['tasks'] if t.get('latest_start_at'))
    row = next(r for r in plan['schedule'] if r['task_id'] == first['id'])
    assert row['start_at'] == deadline
    state = new_state(plan, NOW)
    state, _ = apply_event(state, {'type': 'release_change', 'target_id': 'chain:post', 'data': {'release_at': deadline + 60}}, NOW)
    with pytest.raises(ValueError, match='无可行'):
        schedule(state, NOW)
    blocked, _ = advance(state, deadline + 3600)
    assert any('固定发运' in (p.get('blocked_reason') or '') for p in blocked['tasks'].values())
    assert next(t for t in state['plan']['tasks'] if t['id'] == first['id'])['window_end'] == first['window_end']
    # An externally supplied candidate cannot bypass fixed departure validation.
    bad = copy.deepcopy(plan['schedule']); next(r for r in bad if r['task_id'] == first['id'])['start_at'] += 60
    assert not validate(new_state(plan, NOW), {'schedule': bad, 'routes': plan['routes']}, NOW)['passed']
    final, _ = advance(new_state(plan, NOW), max(s['end_at'] for s in plan['schedule']) + 10)
    assert final['status'] == 'idle' and final['inventory']['warehouse|chain:finished'] == 0


def test_cross_depot_route_arrives_at_its_real_end_depot():
    source = route_source('Stage2_Balanced:1:1')
    customers = {str(int(float(s['cust_id']))) for s in source['stops'] if s['node_type'] == 'customer'}
    units = int(sum(float(c['demand']) for c in source['customers'] if str(int(float(c['cust_id']))) in customers))
    base = native(units); c = delivery_config(config(base), source, NOW)
    plan = build_chain(base, c, supplies(), logistics=source)
    ret = next(s for s in plan['schedule'] if s['task_id'].endswith(':return'))
    assert ret['to_node'] == 'logistics:depot:2'
    final, _ = advance(new_state(plan, NOW), max(s['end_at'] for s in plan['schedule']) + 10)
    assert final['resources']['logistics:vehicle:13']['location'] == 'logistics:depot:2'


def test_production_sync_cannot_silently_invalidate_confirmed_batch_quantities():
    base = native(); plan = build_chain(base, config(base), supplies())
    with pytest.raises(NewRunRequired, match='数量已变更'):
        synchronize(new_state(plan, NOW), native(3), NOW)


def test_explicit_qmix_process_ids_must_match_current_capabilities():
    base = native(); c = config(base); reference = build_chain(base, c, supplies())
    rows = [s for s in reference['schedule'] if s['task_id'].startswith('chain:unit:')]
    data = [[(r['start_at'] - NOW) / 60, (r['end_at'] - r['start_at']) / 60,
             int(r['resource_id'].split(':')[-1]), int(r['task_id'].split(':')[2]), int(r['task_id'].split(':')[-1])] for r in rows]
    saved = {'id': 'test:five', 'units': 2, 'rows': data, 'version': fingerprint(data)}
    c.update(assembly_mode='saved', assembly_origin_at=NOW, assembly_time_unit='minutes')
    assert build_chain(base, c, supplies(), saved)['chain_summary']['assembly_changes'] == []
    saved['rows'][0][-1] = 99
    with pytest.raises(ValueError, match='明确工序ID'):
        build_chain(base, c, supplies(), saved)


def test_chain_api_saves_draft_checks_source_version_and_archives_explicitly(tmp_path):
    directory = tmp_path / 'data/integration'; directory.mkdir(parents=True)
    (directory / 'purchased_assembly_parts.json').write_text(json.dumps({'parts': []}), encoding='utf-8')
    stock_file = directory / 'purchased_supply_state.json'
    stock_file.write_text(json.dumps({'materials': {}, 'deliveries': [], 'updated_at': NOW}), encoding='utf-8')
    clock = [NOW]; store = MemoryStore(); service = OperationsService(store, clock=lambda: clock[0], tick_seconds=.01)
    doc = tiny_doc(); docs = Collection([doc])
    @asynccontextmanager
    async def lifespan(app):
        await service.start()
        yield
        await service.stop()
    app = FastAPI(lifespan=lifespan)
    app.include_router(create_router(service, docs, Collection(MACHINES), Collection([]), chain_source_root=tmp_path))
    with TestClient(app) as client:
        assert client.get('/api/operations-tools/plans/chain/sources').status_code == 200
        from .test_coherence import contract
        c = contract(config(native(start=NOW + 120)))
        assert client.put('/api/operations-tools/plans/chain/draft', json=c).status_code == 200
        assert client.get('/api/operations-tools/plans/chain/draft').json()['config'] == c
        def preview():
            result = client.post('/api/operations-tools/plans/chain/preview', json=c)
            assert result.status_code == 200, result.text
            return result.json()
        p = preview()
        stock_file.write_text(json.dumps({'materials': {}, 'deliveries': [], 'updated_at': NOW + 1}), encoding='utf-8')
        assert client.post('/api/operations-tools/plans/activate', json={'source': 'chain', 'preview_id': p['preview_id']}).status_code == 409
        p = preview()
        response = client.post('/api/operations-tools/plans/activate', json={'source': 'chain', 'preview_id': p['preview_id']})
        assert response.status_code == 200, response.text
        old = client.get('/api/operations-tools/current').json()['instance']
        assert old['plan']['scope'] == 'chain' and old['plan']['coverage']['delivery'] == 'unbound'
        p = preview()
        assert client.post('/api/operations-tools/plans/activate', json={'source': 'chain', 'preview_id': p['preview_id']}).status_code == 409
        response = client.post('/api/operations-tools/plans/activate', json={'source': 'chain', 'preview_id': p['preview_id'],
                             'confirm_new_run': True, 'previous_run_id': old['run_id']})
        assert response.status_code == 200, response.text
        assert old['run_id'] in store.archives
