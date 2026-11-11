import asyncio
import copy
import json
from contextlib import asynccontextmanager

import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metaforge.operations.api import create_router
from metaforge.operations.coordinator import metrics, schedule
from metaforge.operations.models import new_state
from metaforge.operations.plans import DATA_DIR, normalize_plan, prepare_standard
from metaforge.operations.runtime import advance, apply_event
from metaforge.operations.service import OperationsService
from metaforge.operations.sources import assembly_definitions, production_plan
from metaforge.operations.store import MemoryStore
from metaforge.operations.validator import validate
from .fixtures import prepare_legacy_plan

NOW = 1_800_000_000.0


def source():
    return json.loads((DATA_DIR / 'production_source.json').read_text(encoding='utf-8'))


def test_standard_preserves_all_44_native_operations_equipment_and_saved_times():
    native = source()
    plan = prepare_standard(NOW)
    assert plan['alignment_version'] == 2
    assert plan['source_plan_id'] == native['id']
    assert len([t for t in plan['tasks'] if t['kind'] == 'production']) == 44
    slots = {s['task_id']: s for s in plan['schedule']}
    for t in plan['tasks']:
        if t['kind'] != 'production':
            continue
        ref = t['source_ref']; original = native['jobs'][ref['job_index']]['tasks'][ref['operation_index']]
        assert [a['resource_id'] for a in t['alternatives']] == [f'production:machine:{original["machine_id"]}']
        assert t['alternatives'][0]['duration_seconds'] == original['duration'] * 3600
        assert t['resumable'] is False
        original_row = next(r for r in native['schedule_results']['q']['gantt_data'] if r['job_name'] == native['jobs'][ref['job_index']]['name'] and r['operation_name'] == original['name'])
        assert slots[t['id']]['start_at'] == NOW + original_row['start'] * 3600
        assert slots[t['id']]['end_at'] == NOW + original_row['end'] * 3600
    assert not any(r['id'] in {'M1', 'M2', 'S1', 'S2', 'V1', 'V2'} for r in plan['resources'])


def test_standard_uses_actual_assembly_capabilities_and_logistics_records():
    plan = prepare_standard(NOW)
    defs = assembly_definitions()
    assert len([r for r in plan['resources'] if r['kind'] == 'assembly']) == 18
    for t in plan['tasks']:
        if t['kind'] == 'assembly':
            d = defs[t['source_ref']['process_id']]
            assert [a['resource_id'] for a in t['alternatives']] == [f'assembly:workstation:{ws}' for ws in d.workstation_ids]
            assert all(a['unit_seconds'] == d.standard_time * 60 for a in t['alternatives'])
    vehicle = next(r for r in plan['resources'] if r['kind'] == 'vehicle')
    assert vehicle['source_ref']['id'] == 14 and vehicle['capacity'] == 12
    customer_orders = [o for o in plan['orders'] if o.get('role') != 'component']
    assert [(o['source_ref']['cust_id'], o['quantity']) for o in customer_orders] == [(36, 3), (38, 2)]
    assert all(o['due_at'] is None for o in customer_orders)
    assert plan['baseline_parameters']  # Explicit standards, never mislabelled as native facts.
    assert {s['material_id'] for s in plan['stock']} >= {'compressor', 'circuit_board', 'foam_material', 'packing_box'}
    state = new_state(plan, NOW)
    assert validate(state, {'schedule': plan['schedule'], 'routes': plan['routes'], 'policy': 'original'}, NOW)['passed']
    finished, events = advance(state, NOW + 7 * 86400)
    assert finished['status'] == 'idle'
    assert len([e for e in events if e['type'] == 'task_completed']) == 93
    assert all(q >= -1e-6 for q in finished['inventory'].values())
    assert metrics(finished, [])['unknown_commitments'] == 2


def tiny_doc():
    return {'_id': ObjectId('000000000000000000000001'), 'plan_name': '原计划', 'jobs': [{'name': '原工单', 'quantity': 2,
      'priority': 10, 'tasks': [{'name': '下料', 'machine_id': 0, 'machine_options': [0, 4], 'duration': 2},
                             {'name': '焊接', 'machine_id': 2, 'machine_options': [2], 'duration': 3}]}],
      'schedule_results': {'ts': {'gantt_data': [{'job_name': '原工单', 'operation_id': 0, 'operation_name': '下料', 'machine_id': 0, 'start': 1, 'end': 3},
                                               {'job_name': '原工单', 'operation_id': 1, 'operation_name': '焊接', 'machine_id': 2, 'start': 3, 'end': 6}]}}}


MACHINES = [{'id': mid, 'name': f'原设备{mid}'} for mid in [0, 2, 4]]


def test_native_import_preserves_options_units_and_does_not_invent_downstream_or_due():
    plan = normalize_plan(production_plan(tiny_doc(), MACHINES, [], NOW, solver='ts', time_unit='hours'))
    assert [a['resource_id'] for a in plan['tasks'][0]['alternatives']] == ['production:machine:0', 'production:machine:4']
    assert {a['duration_seconds'] for a in plan['tasks'][0]['alternatives']} == {7200}
    assert plan['schedule'][0]['start_at'] == NOW + 3600
    assert plan['schedule'][1]['end_at'] == NOW + 21600
    assert plan['orders'][0]['due_at'] is None
    assert plan['coverage']['assembly'] == plan['coverage']['delivery'] == 'unbound'
    state = new_state(plan, NOW)
    initial = OperationsService.initial_candidate(state, NOW)
    assert initial['schedule'] == plan['schedule']
    assert validate(state, initial, NOW)['passed']
    assert initial['metrics']['unknown_commitments'] == 1
    changed, _ = apply_event(state, {'type': 'resource_unavailable', 'target_id': 'production:machine:0', 'data': {}}, NOW)
    # The explicitly allowed alternative can serve an unstarted task, but welding cannot move there.
    c = schedule(changed, NOW, 'edd')
    assert next(s for s in c['schedule'] if s['task_id'] == plan['tasks'][0]['id'])['resource_id'] == 'production:machine:4'
    assert next(s for s in c['schedule'] if s['task_id'] == plan['tasks'][1]['id'])['resource_id'] == 'production:machine:2'


def test_shared_tabu_budget_returns_a_complete_sequence_on_expiry():
    from metaforge.problems.jobshop import Job, Task, JobShopProblem
    from metaforge.solvers.tabu_search import TabuSearchSolver
    problem = JobShopProblem([Job([Task(0, 2), Task(1, 3)]), Job([Task(1, 1)])])
    result = TabuSearchSolver(problem).run(time_limit=0)
    assert len(result['best_solution']) == 3
    assert len(result['gantt_data']) == 3
    assert result['history'] == []


def test_native_per_unit_parameters_are_preserved_and_only_remaining_work_changes():
    d = tiny_doc()
    d['jobs'][0]['tasks'][0].update(setup_time=1, unit_time=1)
    rows = d['schedule_results']['ts']['gantt_data']
    rows[0]['end'] = 4; rows[1].update(start=4, end=7)
    plan = normalize_plan(production_plan(d, MACHINES, [], NOW, solver='ts'))
    task = plan['tasks'][0]
    assert task['duration_mode'] == 'per_unit'
    assert all(a['setup_seconds'] == 3600 and a['unit_seconds'] == 3600 for a in task['alternatives'])
    state, _ = advance(new_state(plan, NOW), NOW + 3 * 3600)
    assert state['tasks'][task['id']]['quantity_remaining'] == 1
    before = state['tasks'][task['id']]['work_seconds']
    state, _ = apply_event(state, {'type': 'duration_change', 'target_id': task['id'], 'data': {'resource_id': 'production:machine:0', 'duration_mode': 'per_unit', 'value': 7200}}, NOW + 3 * 3600)
    assert state['tasks'][task['id']]['work_seconds'] == before
    assert state['tasks'][task['id']]['quantity_remaining'] == 1


def test_native_import_rejects_missing_equipment_illegal_gantt_and_continuous_bom():
    d = tiny_doc()
    with pytest.raises(ValueError, match='设备目录'):
        production_plan(d, MACHINES[:2], [], NOW, solver='ts')
    d['schedule_results']['ts']['gantt_data'][1]['machine_id'] = 4
    with pytest.raises(ValueError, match='未授权'):
        production_plan(d, MACHINES, [], NOW, solver='ts')
    d = tiny_doc(); d['jobs'][0]['bom'] = [{'material_id': 'MAT_STEEL', 'consume_mode': 'per_hour'}]
    with pytest.raises(ValueError, match='连续耗料'):
        production_plan(d, MACHINES, [], NOW, solver='ts')


def test_native_gantt_is_validated_instead_of_silently_repaired_on_activation():
    d = tiny_doc()
    d['schedule_results']['ts']['gantt_data'][1]['end'] = 4  # Source says three hours, invalid saved Gantt says one.
    plan = normalize_plan(production_plan(d, MACHINES, [], NOW, solver='ts'))
    state = new_state(plan, NOW)
    c = OperationsService.initial_candidate(state, NOW)
    assert c['schedule'][1]['end_at'] == NOW + 4 * 3600
    assert any(v['code'] == 'duration' for v in validate(state, c, NOW)['violations'])


@pytest.mark.parametrize('hard', [False, True])
def test_logistics_window_constrains_service_start_and_fault_cannot_teleport_through_deadline(hard):
    plan = prepare_standard(NOW)
    delivery = next(t for t in plan['tasks'] if t['id'] == 'logistics:customer:38:delivery')
    row = next(s for s in plan['schedule'] if s['task_id'] == delivery['id'])
    delivery['window_hard'] = hard
    # Native route service may finish after tw_end while starting inside its window.
    assert row['service_start_at'] <= delivery['window_end'] < row['end_at']
    state = new_state(plan, NOW)
    state, _ = advance(state, row['start_at'] + 60)
    state, _ = apply_event(state, {'type': 'resource_unavailable', 'target_id': 'logistics:vehicle:14', 'data': {}}, row['start_at'] + 60)
    state, _ = advance(state, delivery['window_end'] + 600)
    state, _ = apply_event(state, {'type': 'resource_recovered', 'target_id': 'logistics:vehicle:14', 'data': {}}, delivery['window_end'] + 600)
    if hard:
        assert state['tasks'][delivery['id']]['status'] == 'paused'
        assert state['tasks'][delivery['id']].get('service_started_at') is None
        assert '硬收货窗口' in state['tasks'][delivery['id']]['blocked_reason']
    else:
        state, _ = advance(state, delivery['window_end'] + 3 * 3600)
        assert state['tasks'][delivery['id']]['status'] == 'completed'
        assert state['tasks'][delivery['id']]['service_started_at'] > delivery['window_end']
        assert state['tasks'][delivery['id']]['window_late_seconds'] > 0
        assert metrics(state, [])['window_penalty_score'] > 0


class Cursor:
    def __init__(self, rows): self.rows = rows
    def sort(self, *args): return self
    def limit(self, n): return self
    async def to_list(self, n): return copy.deepcopy(self.rows[:n])


class Collection:
    def __init__(self, rows): self.rows = rows
    def find(self, *args): return Cursor(self.rows)
    async def find_one(self, query): return next((copy.deepcopy(r) for r in self.rows if r.get('_id') == query.get('_id')), None)


def test_api_lists_imports_native_plan_and_blocks_source_version_drift():
    documents = Collection([tiny_doc()]); store = MemoryStore()
    service = OperationsService(store, clock=lambda: NOW, tick_seconds=.02)
    @asynccontextmanager
    async def lifespan(app):
        await service.start()
        yield
        await service.stop()
    app = FastAPI(lifespan=lifespan)
    app.include_router(create_router(service, documents, Collection(MACHINES), Collection([])))
    with TestClient(app) as c:
        catalog = c.get('/api/operations-tools/plans/sources').json()['plans']
        assert catalog[0]['id'] == str(tiny_doc()['_id']) and catalog[0]['solvers'] == ['ts']
        body = {'source': 'production', 'plan_id': catalog[0]['id'], 'solver_id': 'ts', 'time_unit': 'minutes'}
        preview = c.post('/api/operations-tools/plans/preview', json=body)
        assert preview.status_code == 200 and preview.json()['can_activate']
        body['source_version'] = preview.json()['source_version']
        documents.rows[0]['jobs'][0]['priority'] = 20
        assert c.post('/api/operations-tools/plans/activate', json=body).status_code == 409
        body.pop('source_version')
        assert c.post('/api/operations-tools/plans/activate', json=body).status_code == 200
        current = c.get('/api/operations-tools/current').json()['instance']
        assert current['source'] == 'production' and current['plan']['scope'] == 'production'
        assert current['schedule'][0]['start_at'] == NOW + 5 + 60
        assert current['resources'][0]['name'] == '原设备0'


def test_legacy_replacement_is_explicit_archived_and_not_allowed_for_aligned_active_run():
    async def run():
        store = MemoryStore(); service = OperationsService(store, clock=lambda: NOW)
        await store.setup()
        await service.submit('activate', {'plan': prepare_legacy_plan(NOW + 5)}, 'old')
        await service.step()
        old, _ = await store.read()
        await service.submit('activate', {'plan': prepare_standard(NOW + 5), 'replace_legacy': True, 'previous_run_id': old['run_id']}, 'replace')
        await service.step()
        new, _ = await store.read()
        assert new['run_id'] != old['run_id'] and new['plan']['alignment_version'] == 2
        assert store.archives[old['run_id']]['plan']['id'] == 'REFRIGERATOR-STANDARD-v1'
        assert store.archives[old['run_id']]['archived_at'] == NOW
        await service.submit('activate', {'plan': prepare_standard(NOW + 5), 'replace_legacy': True, 'previous_run_id': new['run_id']}, 'forbidden')
        await service.step()
        assert (await store.command('forbidden'))['status'] == 'failed'
        assert (await store.read())[0]['run_id'] == new['run_id']
    asyncio.run(run())
