import asyncio
import copy
import time
from contextlib import asynccontextmanager

import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metaforge.operations.api import create_router
from metaforge.operations.models import new_state
from metaforge.operations.plans import normalize_plan, prepare_standard
from metaforge.operations.production_sync import NewRunRequired, synchronize
from metaforge.operations.runtime import advance, apply_event
from metaforge.operations.service import OperationsService
from metaforge.operations.sources import production_plan
from metaforge.operations.store import MemoryStore
from .test_source_alignment import tiny_doc, MACHINES, Collection

NOW = 1_800_000_000.0


def imported(doc=None, materials=None):
    return normalize_plan(production_plan(doc or tiny_doc(), MACHINES, materials or [], NOW, solver='ts', time_unit='minutes'))


def revised(duration=5):
    doc = tiny_doc()
    doc['jobs'][0]['tasks'][1]['duration'] = duration
    doc['schedule_results']['ts']['gantt_data'][1]['end'] = 3 + duration
    return doc


def test_sync_updates_future_work_and_freezes_running_progress():
    state, _ = advance(new_state(imported(), NOW), NOW + 120)
    first, second = [t['id'] for t in state['plan']['tasks']]
    progress = copy.deepcopy(state['tasks'][first])
    updated, summary, _ = synchronize(state, imported(revised()), NOW + 120)
    assert updated['run_id'] == state['run_id'] and updated['plan']['start_at'] == NOW
    assert updated['tasks'][first] == progress
    assert summary['retained_count'] == 1 and summary['updated_count'] == 1
    assert next(t for t in updated['plan']['tasks'] if t['id'] == second)['alternatives'][0]['duration_seconds'] == 300
    assert summary['validation']['passed'] and updated['constraint_version'] == state['constraint_version'] + 1


def test_source_sync_preserves_local_duration_when_source_only_changes_timing():
    state = new_state(imported(), NOW)
    tid = state['plan']['tasks'][1]['id']
    state, _ = apply_event(state, {'type': 'duration_change', 'target_id': tid,
      'data': {'resource_id': 'production:machine:2', 'duration_mode': 'batch', 'value': 420}}, NOW + 30)
    doc = tiny_doc(); doc['schedule_results']['ts']['gantt_data'][1].update(start=4, end=7)
    updated, summary, _ = synchronize(state, imported(doc), NOW + 30)
    task = next(t for t in updated['plan']['tasks'] if t['id'] == tid)
    assert task['alternatives'][0]['duration_seconds'] == 420
    assert next(r for r in updated['schedule'] if r['task_id'] == tid)['end_at'] == NOW + 11 * 60
    assert summary['validation']['passed']


def test_conflicting_source_and_local_parameter_changes_do_not_overwrite_either():
    state = new_state(imported(), NOW); tid = state['plan']['tasks'][1]['id']
    state, _ = apply_event(state, {'type': 'duration_change', 'target_id': tid,
      'data': {'resource_id': 'production:machine:2', 'duration_mode': 'batch', 'value': 420}}, NOW + 30)
    before = copy.deepcopy(state)
    with pytest.raises(NewRunRequired, match='均被修改'):
        synchronize(state, imported(revised()), NOW + 30)
    assert state == before


def test_sync_does_not_restore_failed_machine_or_replenish_existing_inventory():
    materials = [{'id': 'MAT_STEEL', 'current_stock': 500}]
    state = new_state(imported(materials=materials), NOW)
    state['inventory']['production|MAT_STEEL'] = 123
    state, _ = apply_event(state, {'type': 'resource_unavailable', 'target_id': 'production:machine:0',
                                  'data': {'expected_recovery_at': NOW + 80}}, NOW + 30)
    doc = tiny_doc(); doc['schedule_results']['ts']['gantt_data'][0]['machine_id'] = 4
    updated, _, _ = synchronize(state, imported(doc, [{'id': 'MAT_STEEL', 'current_stock': 999}]), NOW + 30)
    assert updated['inventory']['production|MAT_STEEL'] == 123
    assert updated['resources']['production:machine:0']['available'] is False
    assert updated['schedule'][0]['resource_id'] == 'production:machine:4'


def test_unchanged_sync_never_reverts_operations_adjustments_or_revises_schedule():
    state = new_state(imported(), NOW); tid = state['plan']['tasks'][1]['id']
    state, _ = apply_event(state, {'type': 'duration_change', 'target_id': tid,
      'data': {'resource_id': 'production:machine:2', 'duration_mode': 'batch', 'value': 420}}, NOW + 30)
    before = copy.deepcopy(state['schedule'])
    result, summary, _ = synchronize(state, imported(), NOW + 30)
    assert summary['unchanged']
    assert result['schedule'] == before
    assert result['constraint_version'] == state['constraint_version']


def test_standard_chain_can_bind_its_database_source_without_resetting_downstream():
    plan = prepare_standard(NOW)
    state, _ = advance(new_state(plan, NOW), NOW + 120)
    from .test_source_alignment import source
    src = source()
    native = normalize_plan(production_plan(src, src['machines'], [], NOW, solver='q'))
    old_downstream = [copy.deepcopy(t) for t in plan['tasks'] if t['kind'] != 'production']
    updated, summary, _ = synchronize(state, native, NOW + 120)
    assert summary['unchanged'] and updated['run_id'] == state['run_id']
    assert [t for t in updated['plan']['tasks'] if t['kind'] != 'production'] == old_downstream
    assert len(updated['tasks']) == 93


def make_app():
    documents = Collection([tiny_doc()]); store = MemoryStore(); clock = [NOW]
    service = OperationsService(store, clock=lambda: clock[0], tick_seconds=.02)
    @asynccontextmanager
    async def lifespan(app):
        await service.start()
        yield
        await service.stop()
    app = FastAPI(lifespan=lifespan)
    app.include_router(create_router(service, documents, Collection(MACHINES), Collection([]), allow_implicit_standard=False))
    return app, documents, store, clock


def activate(client):
    body = {'source': 'production', 'plan_id': str(tiny_doc()['_id']), 'solver_id': 'ts', 'time_unit': 'minutes'}
    assert client.post('/api/operations-tools/plans/activate', json=body).status_code == 200
    current = client.get('/api/operations-tools/current').json()['instance']
    return body, current


def test_api_detects_saved_update_previews_and_syncs_without_resetting_clock():
    app, documents, store, clock = make_app()
    with TestClient(app) as client:
        assert client.post('/api/operations-tools/plans/activate', json={}).status_code == 422
        body, old = activate(client)
        assert client.get('/api/operations-tools/plans/production/status').json()['status'] == 'synced'
        clock[0] += 100; time.sleep(.08)
        documents.rows[0] = revised()
        assert client.get('/api/operations-tools/plans/production/status').json()['has_updates']
        preview = client.post('/api/operations-tools/plans/production/preview-sync', json={**body, 'run_id': old['run_id']}).json()
        assert preview['mode'] == 'sync' and preview['summary']['retained_count'] == 1
        before = client.get('/api/operations-tools/current').json()['instance']
        clock[0] += 10
        response = client.post('/api/operations-tools/plans/production/sync', json={'run_id': old['run_id'], 'preview_id': preview['preview_id']})
        assert response.status_code == 200, response.text
        after = client.get('/api/operations-tools/current').json()['instance']
        assert after['run_id'] == old['run_id'] and after['plan']['start_at'] == old['plan']['start_at']
        assert after['last_tick_at'] >= before['last_tick_at']
        assert client.get('/api/operations-tools/plans/production/status').json()['status'] == 'synced'


def test_api_blocks_source_or_operations_change_after_preview():
    app, documents, store, clock = make_app()
    with TestClient(app) as client:
        body, old = activate(client)
        documents.rows[0] = revised()
        preview = client.post('/api/operations-tools/plans/production/preview-sync', json={**body, 'run_id': old['run_id']}).json()
        documents.rows[0]['jobs'][0]['priority'] = 33
        result = client.post('/api/operations-tools/plans/production/sync', json={'run_id': old['run_id'], 'preview_id': preview['preview_id']})
        assert result.status_code == 409
        preview = client.post('/api/operations-tools/plans/production/preview-sync', json={**body, 'run_id': old['run_id']}).json()
        client.post('/api/operations-tools/events', json={'run_id': old['run_id'], 'type': 'resource_unavailable', 'target_id': 'production:machine:0', 'data': {}})
        assert client.post('/api/operations-tools/plans/production/sync', json={'run_id': old['run_id'], 'preview_id': preview['preview_id']}).status_code == 409


def test_other_saved_plan_is_selectable_and_requires_explicit_archived_cutover():
    app, documents, store, clock = make_app()
    second = tiny_doc(); second['_id'] = ObjectId('000000000000000000000002'); second['plan_name'] = '另一份排程'
    documents.rows.append(second)
    with TestClient(app) as client:
        body, old = activate(client)
        new = {**body, 'plan_id': str(second['_id']), 'run_id': old['run_id']}
        preview = client.post('/api/operations-tools/plans/production/preview-sync', json=new).json()
        assert preview['mode'] == 'new_run' and preview['requires_new_run']
        assert client.post('/api/operations-tools/plans/activate', json=new).status_code == 409
        assert client.post('/api/operations-tools/plans/activate', json={**new, 'confirm_new_run': True, 'previous_run_id': old['run_id']}).status_code == 200
        after = client.get('/api/operations-tools/current').json()['instance']
        assert after['plan']['source_plan_id'] == str(second['_id']) and after['run_id'] != old['run_id']
        assert old['run_id'] in store.archives
