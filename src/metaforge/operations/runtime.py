"""Pure event-driven execution on a real UTC clock. Queries never call advance()."""
from __future__ import annotations

import copy
from collections import defaultdict

from .models import number, timestamp, material_key, timing

EPS = 1e-6


def _open(resource, at):
    return resource["available"] and any(a <= at < b for a, b in resource["working_windows"])


def _remaining(task, progress):
    rid = progress["resource_id"]
    if task["kind"] in {"delivery", "return"}:
        return progress.get("setup_remaining", 0) + progress.get("batch_remaining", 0)
    return sum(timing(task, rid, progress))


def _consume_work(task, progress, seconds, at=None):
    setup = min(seconds, progress.get("setup_remaining", 0))
    progress["setup_remaining"] -= setup
    seconds -= setup
    progress["work_seconds"] += setup + seconds
    if task.get("duration_mode") == "per_unit":
        alt = next(a for a in task["alternatives"] if a["resource_id"] == progress["resource_id"])
        progress["quantity_remaining"] = max(0.0, progress["quantity_remaining"] - seconds / float(alt["unit_seconds"]))
    else:
        if task['kind'] == 'delivery' and at is not None and progress.get('service_started_at') is None:
            before_service = max(0, progress.get('batch_remaining', 0) - task.get('service_seconds', 0))
            if seconds >= before_service - EPS:
                progress['service_started_at'] = at + setup + before_service
                if task.get('window_end') is not None:
                    progress['window_late_seconds'] = max(0, progress['service_started_at'] - task['window_end'])
        progress["batch_remaining"] = max(0.0, progress.get("batch_remaining", 0) - seconds)
        alt = next(a for a in task["alternatives"] if a["resource_id"] == progress["resource_id"])
        base = float(alt.get("duration_seconds", 0))
        if base > 0:
            progress["fraction_remaining"] = min(1.0, progress["batch_remaining"] / base)
        else:
            progress["fraction_remaining"] = progress["batch_remaining"] / max(EPS, progress["batch_remaining"] + progress["work_seconds"])


def advance(state: dict, target: float) -> tuple[dict, list]:
    state = copy.deepcopy(state)
    cursor = state["last_tick_at"]
    if target < cursor:
        state["clock_warning"] = "服务器时间早于最近已处理时刻，状态不回滚，等待时间对齐"
        return state, []
    state.pop("clock_warning", None)
    tasks = {t["id"]: t for t in state["plan"]["tasks"]}
    rows = {s["task_id"]: s for s in state["schedule"]}
    log = []
    def record(kind, tid, at, **extra):
        log.append({"type": kind, "target_id": tid, "occurred_at": at, "source": "standard_execution", **extra})
    def transition(at):
        for supply in state["plan"]["supplies"]:
            if supply["id"] not in state["received_supplies"] and supply["available_at"] <= at + EPS:
                key = f"{supply['location']}|{supply['material_id']}"
                state["inventory"][key] = state["inventory"].get(key, 0) + supply["quantity"]
                state["received_supplies"].append(supply["id"])
                record("supply_received", supply["id"], at, quantity=supply["quantity"])
        for tid, p in state["tasks"].items():
            if p["status"] == "running" and _remaining(tasks[tid], p) <= EPS:
                p["status"], p["actual_end_at"] = "completed", at
                if p["segments"]:
                    p["segments"][-1]["end_at"] = at
                for line in tasks[tid].get("outputs", []):
                    key = material_key(line, p["resource_id"])
                    state["inventory"][key] = state["inventory"].get(key, 0) + line["quantity"]
                if tasks[tid]["kind"] in {"transport", "delivery", "return"}:
                    state["resources"][p["resource_id"]]["location"] = rows[tid]["to_node"]
                record("task_completed", tid, at)
            elif p["status"] == "running" and not _open(state["resources"][p["resource_id"]], at):
                p["status"] = "paused"
                if p["segments"]:
                    p["segments"][-1]["end_at"] = at
                record("task_paused", tid, at, reason="资源不可用或班次结束")
        occupied = {p["resource_id"] for p in state["tasks"].values() if p["status"] == "running"}
        for tid, row in sorted(rows.items(), key=lambda x: (x[1]["start_at"], x[0])):
            p, t = state["tasks"][tid], tasks[tid]
            if p["status"] not in {"pending", "paused", "blocked"}:
                continue
            p["blocked_reason"] = None
            rid = row["resource_id"]
            if row["start_at"] > at + EPS or t["release_at"] > at + EPS:
                continue
            if not _open(state["resources"][rid], at) or rid in occupied:
                p["blocked_reason"] = "资源不可用、在岗时间未到或仍被占用"
                continue
            deps = t.get("predecessors", []) + row.get("route_predecessors", [])
            if any(state["tasks"][d]["status"] != "completed" or state["tasks"][d]["actual_end_at"] + (t.get("transfer_seconds", 0) if d in t.get("predecessors", []) else 0) > at + EPS for d in deps):
                p["blocked_reason"] = "前置任务、转运或车辆前序未完成"
                continue
            requirements = defaultdict(float)
            for line in t.get("inputs", []):
                requirements[material_key(line, rid)] += line["quantity"]
            if not p["inputs_consumed"] and any(state["inventory"].get(k, 0) < q - EPS for k, q in requirements.items()):
                p["blocked_reason"] = "实际合格物料/成品不足，预计到达不等于实际收货"
                continue
            if p["resource_id"] and p["resource_id"] != rid and not t.get("resumable", False):
                p["blocked_reason"] = "当前工艺不允许在制转机"
                continue
            if t["kind"] == "loading" and state["resources"][rid].get("location") != t.get("at_node", "D"):
                p["blocked_reason"] = "车辆尚未返回装车地点"
                continue
            if t["kind"] in {"delivery", "return"} and p["status"] != "paused" and state["resources"][rid].get("location") != row.get("from_node"):
                p["blocked_reason"] = "车辆当前位置与计划起点不符"
                continue
            if t['kind'] == 'transport' and not p['inputs_consumed'] and state['resources'][rid].get('location') != t['from_node']:
                p['blocked_reason'] = '入厂车辆未到达供给地点，不能跨地点瞬移'
                continue
            setup, work = timing(t, rid, p)
            if p['status'] == 'pending' and (at > t.get('latest_start_at', float('inf')) + EPS or at + setup + work > t.get('latest_end_at', float('inf')) + EPS):
                p['blocked_reason'] = '已错过固定发运/交接时限，请确认新的安排'
                continue
            if t["kind"] in {"delivery", "return"}:
                if p["status"] == "paused":
                    work = p["batch_remaining"]
                else:
                    road = state["plan"]["travel_seconds"][f"{row['from_node']}|{row['to_node']}"]
                    arrival = at + road
                    work = road + max(0, t.get("window_start", arrival) - arrival) + t.get("service_seconds", 0)
                window_check = (p.get('service_started_at') or at + setup + max(0, work - t.get('service_seconds', 0))) if t.get('window_policy') == 'service_start' else at + setup + work
                if t.get('window_hard', True) and window_check > t.get("window_end", float("inf")) + EPS:
                    p["blocked_reason"] = "当前已经无法满足硬收货窗口，需重新协调"
                    continue
            if not p["inputs_consumed"]:
                for key, qty in requirements.items():
                    state["inventory"][key] = state["inventory"].get(key, 0) - qty
                p["inputs_consumed"] = True
            p["resource_id"], p["setup_remaining"] = rid, setup
            if t.get("duration_mode") != "per_unit":
                p["batch_remaining"] = work
            p["status"] = "running"
            p["actual_start_at"] = p["actual_start_at"] if p["actual_start_at"] is not None else at
            p["segments"].append({"resource_id": rid, "start_at": at, "end_at": None})
            occupied.add(rid)
            record("task_started", tid, at)
    for _ in range(20000):
        transition(cursor)
        if cursor >= target - EPS:
            break
        future = [target]
        for tid, p in state["tasks"].items():
            if p["status"] == "running":
                future.append(cursor + max(EPS, _remaining(tasks[tid], p)))
            if p["status"] != "completed":
                t = tasks[tid]
                for at in [t["release_at"], rows.get(tid, {}).get("start_at", target)]:
                    if at > cursor + EPS:
                        future.append(at)
                for d in t.get("predecessors", []):
                    end = state["tasks"][d].get("actual_end_at")
                    if end is not None and end + t.get("transfer_seconds", 0) > cursor + EPS:
                        future.append(end + t.get("transfer_seconds", 0))
        for r in state["resources"].values():
            future.extend(at for window in r["working_windows"] for at in window if cursor + EPS < at <= target)
        future.extend(s["available_at"] for s in state["plan"]["supplies"] if s["id"] not in state["received_supplies"] and s["available_at"] > cursor + EPS)
        nxt = min(future)
        elapsed = nxt - cursor
        for tid, p in state["tasks"].items():
            if p["status"] == "running":
                _consume_work(tasks[tid], p, elapsed, at=cursor)
        cursor = nxt
    else:
        state["status"] = "recovering"
    state["last_tick_at"] = cursor
    if all(p["status"] == "completed" for p in state["tasks"].values()):
        state["status"] = "idle"
    elif state["status"] != "recovering":
        state["status"] = "running"
    return state, log


def apply_event(state: dict, event: dict, now: float) -> tuple[dict, list]:
    effective_at = max(state["last_tick_at"], min(now, timestamp(event.get("occurred_at", now))))
    state, transitions = advance(state, effective_at)
    typ, target = event["type"], event.get("target_id")
    plan = state["plan"]
    task_map = {t["id"]: t for t in plan["tasks"]}
    data = event.get("data") or {}
    if typ in {"resource_unavailable", "resource_recovered"}:
        if target not in state["resources"]:
            raise ValueError("资源不存在")
        r = state["resources"][target]
        r["available"] = typ == "resource_recovered"
        r["expected_recovery_at"] = timestamp(data["expected_recovery_at"]) if data.get("expected_recovery_at") and not r["available"] else None
        if r["expected_recovery_at"] is not None and r["expected_recovery_at"] <= now:
            raise ValueError("预计恢复必须晚于当前服务器时间；实际恢复请使用确认恢复")
        for tid, p in state["tasks"].items():
            if p["status"] == "running" and p["resource_id"] == target and not r["available"]:
                p["status"] = "paused"
                p["segments"][-1]["end_at"] = effective_at
    elif typ == "duration_change":
        if target not in task_map or task_map[target]["kind"] not in {"production", "assembly"}:
            raise ValueError("请选择生产/组装的具体工序")
        t, p = task_map[target], state["tasks"][target]
        if p["status"] == "completed":
            raise ValueError("已完成工序不可改写")
        mode = data.get("duration_mode", t["duration_mode"])
        if mode != t["duration_mode"]:
            raise ValueError("运行中不能混用单件和整批口径，请按当前工时口径输入")
        field = "unit_seconds" if mode == "per_unit" else "duration_seconds"
        value = number(data.get("value"), "工序时间（秒）", 0.001)
        selected = data.get("resource_id")
        options = [a for a in t["alternatives"] if not selected or a["resource_id"] == selected]
        if not options:
            raise ValueError("工序候选资源不存在")
        for a in options:
            if p["status"] != "pending" and p["resource_id"] == a["resource_id"] and mode == "batch":
                p["batch_remaining"] = value * p["fraction_remaining"]
            a[field] = value
    elif typ in {"supply_delay", "supply_quantity"}:
        supply = next((s for s in plan["supplies"] if s["id"] == target), None)
        if not supply or target in state["received_supplies"]:
            raise ValueError("仅可修改尚未实际收货的供给批次")
        if typ == "supply_delay":
            supply["available_at"] = timestamp(data["available_at"])
            if supply["available_at"] < now:
                raise ValueError("预计到达须为当前或未来时间；实际收货使用反馈")
        else:
            supply["quantity"] = number(data["quantity"], "确认供给数量")
    elif typ == "inventory_count":
        if not data.get("material_id") or not data.get("location"):
            raise ValueError("请指定物料和库位")
        key = f"{data['location']}|{data['material_id']}"
        if key not in state["inventory"]:
            raise ValueError("库位物料不存在，不可凭空新增库存")
        state["inventory"][key] = number(data["quantity"], "确认现存数量")
    elif typ in {"release_change", "service_change", "window_change"}:
        if target not in task_map or state["tasks"][target]["status"] != "pending":
            raise ValueError("只可修改尚未开工的任务")
        t = task_map[target]
        if typ == "release_change":
            t["release_at"] = timestamp(data["release_at"])
            if t.get('latest_start_at') is not None and t['kind'] in {'transport', 'delivery'}:
                # An explicit new departure is a logged operations decision, not an automatic window shift.
                t['latest_start_at'] = t['release_at']
                if t['kind'] == 'delivery':
                    group = next((g for g in state['plan']['route_groups'] if target == g['delivery_tasks'][0]), None)
                    if group:
                        next(x for x in state['plan']['tasks'] if x['id'] == group['loading_task'])['latest_end_at'] = t['release_at']
        elif typ == "service_change":
            if t["kind"] != "delivery":
                raise ValueError("请选择客户配送任务")
            t["service_seconds"] = number(data["seconds"], "服务时间")
        else:
            if t["kind"] != "delivery":
                raise ValueError("请选择客户配送任务")
            t["window_start"], t["window_end"] = timestamp(data["window_start"]), timestamp(data["window_end"])
            if t["window_end"] <= t["window_start"]:
                raise ValueError("收货结束须晚于开始")
    elif typ == "travel_change":
        key = f"{data.get('from_node')}|{data.get('to_node')}"
        if key not in plan["travel_seconds"]:
            raise ValueError("请选择已有路段")
        plan["travel_seconds"][key] = number(data["seconds"], "行驶时间（秒）", 0.001)
    elif typ == "order_change":
        order = next((o for o in plan["orders"] if o["id"] == target), None)
        if not order:
            raise ValueError("订单不存在")
        state.setdefault("initial_commitments", {}).setdefault(target, {k: order[k] for k in ("due_at", "quantity", "priority")})
        if data.get("due_at"):
            order["due_at"] = timestamp(data["due_at"])
        if data.get("priority") is not None:
            order["priority"] = number(data["priority"], "优先级", 0.001)
    else:
        raise ValueError("未知变化类型")
    state["constraint_version"] += 1
    state["event_seq"] += 1
    state["last_event"] = {**copy.deepcopy(event), "occurred_at": timestamp(event.get("occurred_at", now)), "received_at": event.get("received_at", now),
                           "applied_at": now, "late_report": timestamp(event.get("occurred_at", now)) < now - 2}
    state, after = advance(state, now)
    return state, transitions + after
