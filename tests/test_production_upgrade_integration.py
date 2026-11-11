"""Upstream production upgrade must preserve existing execution and recommendation semantics."""

import asyncio
import copy
from datetime import datetime, timedelta, timezone

from metaforge.services import production_execution as execution
from metaforge.services.schedule_summary import candidates_to_schedule_results


class ExecutionCollection:
    def __init__(self, doc):
        self.doc = copy.deepcopy(doc)

    async def find_one(self, query):
        return copy.deepcopy(self.doc)

    async def replace_one(self, query, doc, **kwargs):
        self.doc = copy.deepcopy(doc)


def execution_doc():
    return {
        "_id": execution.ACTIVE_ID,
        "status": "running",
        "started_at_wall": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "sim_speed": 60,
        "makespan": 4,
        "sim_time": 0,
    }


def test_scheduled_event_at_completion_fires_before_marking_completed(monkeypatch):
    doc = execution_doc()
    doc["scheduled_event"] = {
        "event_type": "insert_order", "status": "pending", "trigger_at": 4,
    }
    collection = ExecutionCollection(doc)
    calls = []

    async def fire_event(coll, current):
        assert current["status"] == "running"
        assert coll.doc["status"] == "running"
        calls.append(current["sim_time"])
        updated = {
            **current,
            "status": "paused",
            "makespan": 8,
            "sim_time_frozen": 4,
            "scheduled_event": {**current["scheduled_event"], "status": "fired"},
        }
        await coll.replace_one({}, updated)
        return updated

    monkeypatch.setattr(execution, "maybe_fire_scheduled_event", fire_event)
    result = asyncio.run(execution.get_state(collection))
    assert calls == [4]
    assert result["status"] == "paused"
    assert result["makespan"] == 8


def test_normal_completion_still_generates_assembly_readiness(monkeypatch):
    from metaforge.services import assembly_readiness

    collection = ExecutionCollection(execution_doc())
    orders, readiness = object(), object()
    calls = []

    async def generate(execution_coll, orders_coll, readiness_coll):
        assert execution_coll.doc["status"] == "completed"
        calls.append((orders_coll, readiness_coll))

    monkeypatch.setattr(assembly_readiness, "try_auto_generate_readiness", generate)
    result = asyncio.run(execution.get_state(collection, orders_coll=orders, readiness_coll=readiness))
    assert result["status"] == "completed"
    assert calls == [(orders, readiness)]


def test_legacy_schedule_map_uses_package_recommendation():
    candidates = [
        {"schedule_id": "illegal_fast", "gantt_data": [{"end": 1}], "metrics": {"makespan": 1}},
        {"schedule_id": "valid", "gantt_data": [{"end": 4}], "metrics": {"makespan": 4}},
    ]
    results = candidates_to_schedule_results(candidates, "valid")
    assert list(results) == ["valid"]
    assert results["valid"]["best_score"] == 4
    assert candidates_to_schedule_results(candidates, None) == {}
