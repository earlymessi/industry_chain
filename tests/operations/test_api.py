import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from metaforge.operations.api import create_router
from metaforge.operations.coordinator import schedule
from metaforge.operations.validator import validate
from metaforge.operations.service import OperationsService
from metaforge.operations.store import MemoryStore
from .fixtures import prepare_legacy_plan

NOW = 1_800_000_000.0


def client_app():
    clock = [NOW]
    store = MemoryStore()
    def slow_solver(state, now, timeout):
        time.sleep(0.4)
        c = schedule(state, now, "edd")
        c["id"] = "edd"
        c["validation"] = validate(state, c, now)
        return {"candidates": [c], "recommended_id": "edd", "searched": 1}
    service = OperationsService(store, clock=lambda: clock[0], tick_seconds=0.02, solver=slow_solver)
    @asynccontextmanager
    async def lifespan(app):
        await service.start()
        yield
        await service.stop()
    app = FastAPI(lifespan=lifespan)
    app.include_router(create_router(service, standard_factory=prepare_legacy_plan))
    return app, clock


def wait_job(client, jid):
    for _ in range(100):
        job = client.get(f"/api/operations-tools/adjustments/{jid}").json()
        if job["status"] in {"done", "failed"}:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not complete")


def test_api_activation_event_idempotency_and_no_reset():
    app, clock = client_app()
    with TestClient(app) as c:
        assert c.get('/api/operations-tools/current').json()['instance'] is None
        body = {"request_id": "activation"}
        assert c.post('/api/operations-tools/plans/activate', json=body).status_code == 200
        before = c.get('/api/operations-tools/current').json()['instance']
        assert c.post('/api/operations-tools/plans/activate', json=body).status_code == 200
        assert c.post('/api/operations-tools/plans/activate', json={"request_id": "new"}).status_code == 409
        clock[0] += 120
        time.sleep(.08)
        event = {"run_id": before['run_id'], "request_id": "fault", "type": "resource_unavailable", "target_id": "M1", "data": {}, "reason": "fixture"}
        assert c.post('/api/operations-tools/events', json=event).status_code == 200
        first = c.get('/api/operations-tools/current').json()['instance']
        assert c.post('/api/operations-tools/events', json=event).status_code == 200
        second = c.get('/api/operations-tools/current').json()['instance']
        assert first['event_seq'] == second['event_seq'] == 1
        assert first['run_id'] == before['run_id']
        assert not next(r for r in second['resources'] if r['id']=='M1')['available']


def test_async_solver_does_not_stop_execution_and_revalidates_late_apply():
    app, clock = client_app()
    with TestClient(app) as c:
        c.post('/api/operations-tools/plans/activate', json={})
        clock[0] += 120
        time.sleep(.08)
        before = c.get('/api/operations-tools/current').json()['instance']
        jid = c.post('/api/operations-tools/adjustments', json={"run_id": before['run_id']}).json()['id']
        time.sleep(.05)
        clock[0] += 30
        time.sleep(.08)
        current = c.get('/api/operations-tools/current').json()
        assert current['server_timestamp'] == clock[0]
        assert sum(t['work_seconds'] for t in current['instance']['tasks']) > sum(t['work_seconds'] for t in before['tasks'])
        job = wait_job(c, jid)
        assert job['status'] == 'done'
        clock[0] += 10
        applied = c.post(f'/api/operations-tools/adjustments/{jid}/apply', json={"run_id": before['run_id'], "candidate_id": "edd"})
        assert applied.status_code == 200, applied.text
        final = c.get('/api/operations-tools/current').json()['instance']
        assert final['plan_revision'] == 2
        assert final['last_adjustment']['validation']['passed']
        assert all(s['start_at'] >= clock[0] for s in final['schedule'])


def test_key_change_blocks_old_candidate_and_assistant_does_not_mutate():
    app, clock = client_app()
    with TestClient(app) as c:
        c.post('/api/operations-tools/plans/activate', json={})
        state = c.get('/api/operations-tools/current').json()['instance']
        jid = c.post('/api/operations-tools/adjustments', json={"run_id": state['run_id']}).json()['id']
        assert wait_job(c, jid)['status'] == 'done'
        draft = c.post('/api/operations-tools/assistant', json={"message": "M1 故障20分钟", "use_llm": False}).json()
        assert draft['prepared_event']['draft']['data']['expected_recovery_at'] == clock[0] + 1200
        assert c.get('/api/operations-tools/current').json()['instance']['event_seq'] == 0
        expected = c.post('/api/operations-tools/assistant', json={"message": "M1 故障，预计20分钟恢复", "use_llm": False}).json()
        assert expected['prepared_event']['draft']['type'] == 'resource_unavailable'
        assert expected['prepared_event']['draft']['data']['expected_recovery_at'] == clock[0] + 1200
        confirmed = c.post('/api/operations-tools/assistant', json={"message": "M1 已确认恢复", "use_llm": False}).json()
        assert confirmed['prepared_event']['draft']['type'] == 'resource_recovered'
        event = {"run_id": state['run_id'], "type": "resource_unavailable", "target_id": "M1", "data": {}}
        assert c.post('/api/operations-tools/events', json=event).status_code == 200
        result = c.post(f'/api/operations-tools/adjustments/{jid}/apply', json={"run_id": state['run_id'], "candidate_id": "edd"})
        assert result.status_code == 409


def test_future_events_do_not_block_immediate_commands():
    app, clock = client_app()
    with TestClient(app) as c:
        c.post('/api/operations-tools/plans/activate', json={})
        run = c.get('/api/operations-tools/current').json()['instance']['run_id']
        future = {"run_id": run, "type": "resource_unavailable", "target_id": "M1", "data": {}, "scheduled_at": NOW + 600}
        response = c.post('/api/operations-tools/events', json=future)
        assert response.status_code == 202
        immediate = {"run_id": run, "type": "resource_unavailable", "target_id": "M2", "data": {}}
        assert c.post('/api/operations-tools/events', json=immediate).status_code == 200
        state = c.get('/api/operations-tools/current').json()['instance']
        assert next(r for r in state['resources'] if r['id']=='M1')['available']
        clock[0] += 600
        time.sleep(.08)
        state = c.get('/api/operations-tools/current').json()['instance']
        assert not next(r for r in state['resources'] if r['id']=='M1')['available']
