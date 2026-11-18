"""Replanning remaining work must preserve the already executed departure."""
import copy

import pytest

from metaforge.operations.coordinator import Infeasible, schedule
from metaforge.operations.models import new_state
from metaforge.operations.runtime import advance, apply_event
from metaforge.operations.validator import validate
from .test_full_baseline import NOW, build, configured


def in_transit():
    plan = build(configured())
    task = next(t for t in plan["tasks"] if t["id"] == "inbound:CASE-SUPPLIER-0")
    now = task["latest_start_at"] + 120
    state, _ = advance(new_state(plan, NOW), now)
    assert state["tasks"][task["id"]]["status"] == "running"
    return state, task, now


@pytest.mark.parametrize("policy", ["original", "edd", "spt"])
def test_departed_supplier_can_be_replanned_without_restarting_trip(policy):
    state, task, now = in_transit()
    progress = copy.deepcopy(state["tasks"][task["id"]])
    candidate = schedule(state, now, policy)
    assert validate(state, candidate, now)["passed"]
    row = next(s for s in candidate["schedule"] if s["task_id"] == task["id"])
    assert row["start_at"] == now
    assert row["end_at"] == pytest.approx(progress["actual_start_at"] + 3300)
    assert state["tasks"][task["id"]] == progress
    state["schedule"], state["routes"] = candidate["schedule"], candidate["routes"]
    final, events = advance(state, max(s["end_at"] for s in candidate["schedule"]) + 1)
    assert final["status"] == "idle"
    assert not any(e["type"] == "task_started" and e["target_id"] == task["id"] for e in events)
    assert all(q >= -1e-6 for q in final["inventory"].values())


def test_paused_trip_retains_actual_departure_and_resumes_remaining_distance():
    state, task, now = in_transit()
    rid = state["tasks"][task["id"]]["resource_id"]
    state, _ = apply_event(state, {"type": "resource_unavailable", "target_id": rid,
        "data": {"expected_recovery_at": now + 60}}, now)
    assert state["tasks"][task["id"]]["status"] == "paused"
    candidate = schedule(state, now)
    assert validate(state, candidate, now)["passed"]
    row = next(s for s in candidate["schedule"] if s["task_id"] == task["id"])
    assert row["start_at"] == now + 60
    assert row["end_at"] == pytest.approx(task["latest_start_at"] + 3300 + 60)


def test_unstarted_trip_that_missed_departure_is_still_rejected():
    plan = build(configured())
    task = next(t for t in plan["tasks"] if t["id"] == "inbound:CASE-SUPPLIER-0")
    state = new_state(plan, NOW)
    rid = task["alternatives"][0]["resource_id"]
    departure = task["latest_start_at"]
    state, _ = apply_event(state, {"type": "resource_unavailable", "target_id": rid,
        "data": {"expected_recovery_at": departure + 60}}, departure - 1)
    now = departure + 30
    state, _ = advance(state, now)
    assert state["tasks"][task["id"]]["actual_start_at"] is None
    assert state["tasks"][task["id"]]["status"] == "pending"
    with pytest.raises(Infeasible, match="错过固定发运"):
        schedule(state, now)
    # Independent validation also rejects a slot moved past the original departure.
    state["resources"][rid]["available"] = True
    candidate = schedule(new_state(plan, NOW), NOW)
    row = next(s for s in candidate["schedule"] if s["task_id"] == task["id"])
    row["start_at"] = now
    assert any(c["code"] == "fixed_deadline" and c["target"] == task["id"]
               for c in validate(state, candidate, now)["violations"])


def test_started_trip_must_still_meet_handover_deadline():
    state, task, now = in_transit()
    candidate = schedule(state, now)
    definition = next(t for t in state["plan"]["tasks"] if t["id"] == task["id"])
    definition["latest_end_at"] = now + 1
    with pytest.raises(Infeasible, match="错过固定发运"):
        schedule(state, now)
    violations = validate(state, candidate, now)["violations"]
    assert any(c["code"] == "fixed_deadline" and c["target"] == task["id"] for c in violations)


def test_validator_does_not_accept_actual_departure_after_commitment():
    state, task, now = in_transit()
    candidate = schedule(state, now)
    state["tasks"][task["id"]]["actual_start_at"] = task["latest_start_at"] + 1
    assert any(c["code"] == "fixed_deadline" and c["target"] == task["id"]
               for c in validate(state, candidate, now)["violations"])
