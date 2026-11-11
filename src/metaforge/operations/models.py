from __future__ import annotations

import copy
import math
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

KINDS = {"production": "生产", "assembly": "组装", "loading": "装车", "delivery": "配送", "return": "返场"}
PARAMETERS = [
    {"type": "resource_unavailable", "label": "资源不可用", "target": "resource", "fields": ["expected_recovery_at"]},
    {"type": "resource_recovered", "label": "确认恢复可用", "target": "resource", "fields": []},
    {"type": "duration_change", "label": "工序耗时变化", "target": "task", "fields": ["duration_mode", "value", "resource_id"]},
    {"type": "supply_delay", "label": "供给预计到达变化", "target": "supply", "fields": ["available_at"]},
    {"type": "supply_quantity", "label": "供给数量变化", "target": "supply", "fields": ["quantity"]},
    {"type": "inventory_count", "label": "确认现存数量", "target": "stock", "fields": ["material_id", "location", "quantity"]},
    {"type": "release_change", "label": "任务最早释放变化", "target": "task", "fields": ["release_at"]},
    {"type": "travel_change", "label": "路段行驶时间变化", "target": "road", "fields": ["from_node", "to_node", "seconds"]},
    {"type": "service_change", "label": "客户服务时间变化", "target": "task", "fields": ["seconds"]},
    {"type": "window_change", "label": "确认客户收货窗口", "target": "task", "fields": ["window_start", "window_end"]},
    {"type": "order_change", "label": "确认订单承诺/优先级变更", "target": "order", "fields": ["due_at", "priority"]},
]


def timestamp(value: Any) -> float:
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("时间必须包含时区，例如 +08:00")
        result = dt.timestamp()
    if not math.isfinite(result):
        raise ValueError("无效时间")
    return result


def iso(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="milliseconds")


def number(value: Any, name: str, minimum: float = 0) -> float:
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f"{name}必须为不小于{minimum}的有限数值")
    return result


def stock_key(location: str, material: str) -> str:
    return f"{location}|{material}"


def material_key(line: dict, resource_id: str) -> str:
    return stock_key(resource_id if line.get("location") == "@resource" else line.get("location", "B"), line["material_id"])


def timing(task: dict, resource_id: str, progress: dict | None = None) -> tuple[float, float]:
    """Return remaining setup and processing seconds, keeping spent work immutable."""
    alt = next((a for a in task["alternatives"] if a["resource_id"] == resource_id), None)
    if alt is None:
        raise ValueError(f"{task['id']}不能在{resource_id}执行")
    setup = float(alt.get("setup_seconds", 0))
    if progress and progress.get("status") != "pending":
        if progress.get("resource_id") == resource_id:
            setup = float(progress.get("setup_remaining", 0))
        else:
            setup += float(task.get("transfer_on_reassign_seconds", 0))
    if task.get("duration_mode") == "per_unit":
        quantity = progress.get("quantity_remaining", task["quantity"]) if progress else task["quantity"]
        processing = float(alt["unit_seconds"]) * float(quantity)
    else:
        fraction = progress.get("fraction_remaining", 1.0) if progress else 1.0
        processing = float(alt["duration_seconds"]) * float(fraction)
    return setup, processing


def new_state(plan: dict, now: float) -> dict:
    plan = copy.deepcopy(plan)
    return {
        "run_id": uuid4().hex, "version": 1, "constraint_version": 1, "plan_revision": 1,
        "activated_at": now, "last_tick_at": min(now, plan["start_at"]), "plan": plan,
        "resources": {r["id"]: {**r, "available": True, "location": r.get("location", "D"), "expected_recovery_at": None} for r in plan["resources"]},
        "tasks": {t["id"]: {"status": "pending", "resource_id": None, "actual_start_at": None, "actual_end_at": None,
                              "quantity_remaining": float(t["quantity"]), "fraction_remaining": 1.0,
                              "setup_remaining": None, "work_seconds": 0.0, "segments": [], "inputs_consumed": False} for t in plan["tasks"]},
        "inventory": {stock_key(x["location"], x["material_id"]): float(x["quantity"]) for x in plan.get("stock", [])},
        "initial_commitments": {o["id"]: {"due_at": o["due_at"], "quantity": o["quantity"], "priority": o["priority"]} for o in plan["orders"]},
        "received_supplies": [], "schedule": copy.deepcopy(plan.get("schedule", [])),
        "routes": copy.deepcopy(plan.get("routes", [])), "event_seq": 0, "last_event": None,
        "metrics": {}, "status": "running", "source": plan["source"],
    }


def public_state(state: dict | None, now: float, health: dict | None = None) -> dict:
    response = {"server_time": iso(now), "server_timestamp": now, "timezone": "Asia/Shanghai", "parameters": PARAMETERS, "health": health or {}, "instance": None}
    if not state:
        return response
    snapshot = copy.deepcopy(state)
    snapshot["tasks"] = [{**t, **state["tasks"][t["id"]]} for t in state["plan"]["tasks"]]
    snapshot["resources"] = list(snapshot["resources"].values())
    snapshot["last_sync_at"] = iso(state["last_tick_at"])
    snapshot["stale_seconds"] = max(0.0, now - state["last_tick_at"])
    snapshot["mode_label"] = ("真实时钟 · 标准计划模拟" if state["source"] == "standard" else "真实时钟 · 前序计划模拟") if state["plan"]["mode"] == "simulation" else "现场反馈"
    snapshot["horizons"] = horizon_summary(state, now)
    response["instance"] = snapshot
    return response


def horizon_summary(state: dict, now: float) -> list[dict]:
    """Only aggregate supplied demand/calendar; absent future data is never zero demand."""
    rows = state.get("forecast", {}).get("schedule", [])
    known = state.get("forecast", {}).get("status") == "available"
    latest_demand = max((o["due_at"] for o in state["plan"]["orders"] if o.get('due_at') is not None), default=now)
    result = []
    for hours, label in [(4, "近端执行"), (24, "当班 / 次日"), (168, "7天批次"), (672, "4周能力")]:
        end = now + hours * 3600
        load = sum(max(0, min(end, s["end_at"]) - max(now, s["start_at"])) for s in rows)
        capacity = sum(max(0, min(end, b) - max(now, a)) for r in state["resources"].values() for a, b in r["working_windows"])
        covered = all(max((b for _, b in r["working_windows"]), default=now) >= end for r in state["resources"].values())
        result.append({"hours": hours, "label": label, "planned_tasks": sum(s["start_at"] < end and s["end_at"] > now for s in rows),
                       "due_orders": sum(now <= o["due_at"] <= end for o in state["plan"]["orders"] if o.get('due_at') is not None),
                       "load_hours": load / 3600 if known else None, "calendar_hours": capacity / 3600, "calendar_complete": covered,
                       "latest_supplied_due_at": latest_demand,
                       "note": "仅汇总已导入需求与日历；远期需求未给定，4周层不发布整月细排" if hours == 672 else "已有任务按工序与交付传播；没有补造后续订单"})
    return result
