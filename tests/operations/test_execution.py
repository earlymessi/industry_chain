import asyncio
import copy

import pytest

from metaforge.operations.models import new_state, timing
from metaforge.operations.plans import normalize_plan
from .fixtures import prepare_legacy_plan as prepare_standard
from metaforge.operations.coordinator import schedule
from metaforge.operations.runtime import advance, apply_event
from metaforge.operations.validator import validate
from metaforge.operations.service import OperationsService
from metaforge.operations.store import MemoryStore, Conflict

START = 1_800_000_000.0


def baseline():
    plan = normalize_plan(prepare_standard(START))
    state = new_state(plan, START)
    candidate = schedule(state, START)
    assert validate(state, candidate, START)["passed"]
    state["schedule"], state["routes"] = candidate["schedule"], candidate["routes"]
    return state


def test_standard_chain_runs_and_never_duplicates_inventory():
    state, events = advance(baseline(), START + 7200)
    assert state["status"] == "idle"
    assert len([e for e in events if e["type"] == "task_completed"]) == 19
    assert all(q >= -1e-6 for q in state["inventory"].values())
    again, events = advance(state, START + 10800)
    assert events == [] and again["inventory"] == state["inventory"]
    assert again["last_tick_at"] == START + 10800


def test_fault_only_pauses_affected_work_and_estimated_recovery_is_not_fact():
    state, _ = advance(baseline(), START + 120)
    m1 = next(t for t, p in state["tasks"].items() if p["status"] == "running" and p["resource_id"] == "M1")
    state, _ = apply_event(state, {"type": "resource_unavailable", "target_id": "M1", "data": {"expected_recovery_at": START + 300}}, START + 120)
    quantity = state["tasks"][m1]["quantity_remaining"]
    state, _ = advance(state, START + 1800)
    assert state["last_tick_at"] == START + 1800
    assert state["tasks"][m1]["status"] == "paused"
    assert state["tasks"][m1]["quantity_remaining"] == quantity
    assert any(p["status"] == "completed" for t, p in state["tasks"].items() if t.startswith("O-B"))
    state, _ = apply_event(state, {"type": "resource_recovered", "target_id": "M1", "data": {}}, START + 1800)
    assert state["tasks"][m1]["status"] == "running"
    assert state["tasks"][m1]["quantity_remaining"] == quantity


def test_unit_duration_change_only_updates_remaining_quantity():
    state = baseline()
    # A-T1: 60s setup + 4 * 120s; two of six pieces remain.
    state, _ = advance(state, START + 540)
    p = state["tasks"]["O-A-T1"]
    assert p["quantity_remaining"] == pytest.approx(2)
    state, _ = apply_event(state, {"type": "duration_change", "target_id": "O-A-T1", "data": {"resource_id": "M1", "duration_mode": "per_unit", "value": 180}}, START + 540)
    task = next(t for t in state["plan"]["tasks"] if t["id"] == "O-A-T1")
    assert timing(task, "M1", state["tasks"][task["id"]]) == (0, 360)
    assert state["tasks"][task["id"]]["work_seconds"] == 540


def test_independent_validator_rejects_omission_duration_and_overlap():
    state = baseline()
    c = schedule(state, START)
    bad = copy.deepcopy(c)
    bad["schedule"].pop()
    assert not validate(state, bad, START)["passed"]
    bad = copy.deepcopy(c)
    bad["schedule"][0]["end_at"] -= 1
    assert any(x["code"] == "duration" for x in validate(state, bad, START)["violations"])
    bad = copy.deepcopy(c)
    rows = [s for s in bad["schedule"] if s["resource_id"] == "M1"]
    rows[1]["start_at"] = rows[0]["start_at"]
    assert any(x["code"] == "exclusive" for x in validate(state, bad, START)["violations"])


def test_supply_delay_keeps_clock_and_never_invents_stock():
    state, _ = apply_event(baseline(), {"type": "supply_delay", "target_id": "SUP-COMP-01", "data": {"available_at": START + 7200}}, START)
    state, _ = advance(state, START + 3600)
    assert "SUP-COMP-01" not in state["received_supplies"]
    assert state["inventory"]["B|COMP"] >= 0
    assert any(p.get("blocked_reason") and "物料" in p["blocked_reason"] for p in state["tasks"].values())


def test_late_fault_does_not_rewind_committed_state():
    state, _ = advance(baseline(), START + 600)
    state, _ = apply_event(state, {"type": "resource_unavailable", "target_id": "M1", "occurred_at": START + 500, "data": {}}, START + 610)
    assert state["last_tick_at"] == START + 610
    assert state["last_event"]["late_report"]


def test_current_read_is_pure_and_activation_idempotent():
    async def exercise():
        clock = [START - 5]
        store = MemoryStore()
        service = OperationsService(store, clock=lambda: clock[0])
        await store.setup()
        plan = prepare_standard(START)
        await service.submit("activate", {"plan": plan}, "one")
        await service.step()
        state, _ = await store.read()
        run_id = state["run_id"]
        version = state["version"]
        clock[0] = START + 600
        first = await service.current()
        assert first["server_timestamp"] == clock[0]
        assert first["instance"]["last_tick_at"] == START - 5
        assert (await store.read())[0]["version"] == version
        await service.step()
        assert (await service.current())["instance"]["run_id"] == run_id
        assert (await service.current())["instance"]["last_tick_at"] == clock[0]
        await service.submit("activate", {"plan": plan}, "one")
        await service.step()
        assert (await store.read())[0]["run_id"] == run_id
    asyncio.run(exercise())


def test_fenced_writer_cannot_commit_after_lease_takeover():
    async def exercise():
        store = MemoryStore()
        old = await store.claim("old", START)
        await store.claim("new", START + 20)
        with pytest.raises(Conflict):
            await store.publish(baseline(), old, START + 20)
    asyncio.run(exercise())


def test_bad_inputs_not_accepted_as_plans():
    plan = prepare_standard(START)
    plan["tasks"][0]["quantity"] = float("nan")
    with pytest.raises(ValueError):
        normalize_plan(plan)


def test_long_supply_delay_escalates_to_capacity_request_without_month_schedule():
    from metaforge.operations.coordinator import choose_scope
    from metaforge.operations.solve_worker import solve
    state, _ = apply_event(baseline(), {"type": "supply_delay", "target_id": "SUP-COMP-01", "data": {"available_at": START + 10 * 86400}}, START)
    assert choose_scope(state, START)["hours"] == 672
    result = solve(state, START)
    assert result["scope"]["capacity_request"] and not result["candidates"]


def test_horizon_summary_does_not_invent_month_capacity_or_demand():
    from metaforge.operations.models import horizon_summary
    state = baseline()
    state["forecast"] = {"status": "available", "schedule": state["schedule"]}
    layers = horizon_summary(state, START)
    assert [x["hours"] for x in layers] == [4, 24, 168, 672]
    assert layers[-1]["calendar_complete"] is False
    assert all(x["due_orders"] == 3 for x in layers)
    assert layers[-1]["load_hours"] == pytest.approx(layers[0]["load_hours"])


def test_disabled_service_keeps_state_and_rejects_commands():
    async def exercise():
        store = MemoryStore()
        head = await store.claim("test", START)
        await store.publish(baseline(), head, START)
        service = OperationsService(store, clock=lambda: START + 10, enabled=False)
        await service.start()
        current = await service.current()
        assert current["health"]["status"] == "disabled"
        assert current["instance"]["last_tick_at"] == START
        with pytest.raises(Conflict):
            await service.submit("event", {})
        await service.stop()
    asyncio.run(exercise())


@pytest.mark.parametrize("scenario", range(6))
def test_standard_operation_scenarios_return_checked_schedule_or_real_shortage(scenario):
    import json
    from pathlib import Path
    cases = json.loads(Path(__file__).with_name('legacy_events.json').read_text(encoding='utf-8'))
    event = cases[scenario]
    if event['type'] == 'supply_delay':
        event['data'] = {'available_at': START + event['data']['offset_from_start_seconds']}
    state, _ = apply_event(baseline(), event, START + 120)
    if event['target_id'] == 'V1':
        with pytest.raises(ValueError):
            schedule(state, START + 120, 'edd')
    else:
        c = schedule(state, START + 120, 'edd')
        assert validate(state, c, START + 120)['passed']


def test_business_commitment_change_keeps_initial_promise():
    from metaforge.operations.coordinator import metrics
    state = baseline()
    initial = state['plan']['orders'][0]['due_at']
    state, _ = apply_event(state, {'type': 'order_change', 'target_id': 'O-A', 'data': {'due_at': initial + 3600}}, START)
    row = next(o for o in metrics(state, state['schedule'])['orders'] if o['order_id'] == 'O-A')
    assert row['original_due_at'] == initial and row['due_at'] == initial + 3600


def test_lost_writer_leaves_command_queued_for_new_owner():
    from metaforge.operations.store import FencedOut
    class LostWriterStore(MemoryStore):
        async def publish(self, *args, **kwargs):
            raise FencedOut('owner changed during commit')
    async def exercise():
        store = LostWriterStore()
        service = OperationsService(store, clock=lambda: START - 5)
        await service.submit('activate', {'plan': prepare_standard(START)}, 'lost')
        await service.step()
        assert (await store.command('lost'))['status'] == 'queued'
        assert service.health['status'] == 'follower'
    asyncio.run(exercise())


def test_future_tasks_outside_rolling_window_are_frozen_and_checked():
    plan = normalize_plan(prepare_standard(START + 6 * 3600))
    state = new_state(plan, START)
    initial = schedule(state, plan['start_at'])
    state['schedule'], state['routes'] = initial['schedule'], initial['routes']
    c = schedule(state, START, 'spt')
    assert c['scope']['hours'] == 4
    assert all(row['horizon_frozen'] for row in c['schedule'])
    assert validate(state, c, START)['passed']
    c['schedule'][0]['start_at'] += 60
    assert any(v['code'] == 'horizon_freeze' for v in validate(state, c, START)['violations'])


def test_partial_delivery_is_not_reported_as_complete_order_forecast():
    from metaforge.operations.coordinator import metrics
    state = baseline()
    duplicate = copy.deepcopy(next(t for t in state['plan']['tasks'] if t['id'] == 'O-A-DELIVERY'))
    duplicate['id'] = 'O-A-SECOND-DELIVERY'
    state['plan']['tasks'].append(duplicate)
    state['tasks'][duplicate['id']] = copy.deepcopy(state['tasks']['O-A-DELIVERY'])
    row = next(o for o in metrics(state, state['schedule'])['orders'] if o['order_id'] == 'O-A')
    assert row['completion_at'] is None and row['delay_seconds'] is None


def test_completed_run_does_not_recommend_empty_gantt_as_adjustment():
    from metaforge.operations.solve_worker import solve
    state, _ = advance(baseline(), START + 7200)
    result = solve(state, START + 7200)
    assert not result['candidates'] and result['recommended_id'] is None
    assert '已完成' in result['message']
