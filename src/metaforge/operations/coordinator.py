"""Bounded, deterministic chain scheduling; solver search runs in a separate process."""
from __future__ import annotations

import copy
import itertools
import random
from collections import defaultdict

from .models import material_key, timing


class Infeasible(ValueError):
    pass


def first_slot(resource: dict, earliest: float, duration: float, bookings: list, *, now: float = 0) -> float:
    if not resource.get("available", True):
        recovery = resource.get("expected_recovery_at")
        if recovery is None or recovery <= now:
            raise Infeasible(f"{resource['id']}不可用，缺少有效恢复估计")
        earliest = max(earliest, recovery)
    for a, b in sorted(resource["working_windows"]):
        t = max(a, earliest)
        for c, d in sorted(bookings):
            if d <= t or c >= b:
                continue
            if t + duration <= c + 1e-7:
                break
            if t < d and t + duration > c:
                t = d
        if t + duration <= b + 1e-7:
            return t
    raise Infeasible(f"{resource['id']}的已知日历没有足够连续时间")


def _material_ready(task, resource_id, earliest, inventory, ledger):
    requirements = defaultdict(float)
    for line in task.get("inputs", []):
        requirements[material_key(line, resource_id)] += float(line["quantity"])
    if not requirements:
        return earliest
    points = sorted({earliest} | {t for key in requirements for t, q in ledger[key] if q > 0 and t >= earliest})
    for candidate in points:
        valid = True
        for key, needed in requirements.items():
            # Protect already allocated future consumption, too.
            later = sorted({candidate} | {t for t, _ in ledger[key] if t >= candidate})
            if any(inventory.get(key, 0) + sum(q for t, q in ledger[key] if t <= at + 1e-7) < needed - 1e-7 for at in later):
                valid = False
                break
        if valid:
            return candidate
    raise Infeasible(f"{task['name']}缺少可分配物料，不能凭ETA虚构数量")


def route_configuration(state: dict, policy: str) -> list:
    plan = state["plan"]
    task_map = {t["id"]: t for t in plan["tasks"]}
    dues = {o["id"]: o.get("due_at") or float('inf') for o in plan["orders"]}
    previous = {r["id"]: r for r in state.get("routes", [])}
    groups = []
    for source in plan["route_groups"]:
        group = copy.deepcopy(source)
        old = previous.get(group["id"], {})
        load_progress = state["tasks"][group["loading_task"]]
        old_order = old.get("stops", group["delivery_tasks"])
        frozen = [tid for tid in old_order if state["tasks"][tid]["status"] in {"completed", "running"}]
        remaining = [tid for tid in old_order if tid not in frozen]
        if policy != "original":
            remaining.sort(key=lambda tid: (dues[task_map[tid]["order_id"]], tid))
            if policy == "spt":
                remaining.reverse()
        group["stops"] = frozen + remaining
        quantity = sum(task_map[t].get("load_units", task_map[t]["quantity"]) for t in group["delivery_tasks"])
        if load_progress["status"] != "pending":
            group["vehicle_id"] = load_progress["resource_id"]
        else:
            choices = [state["resources"][r] for r in group["vehicle_options"] if state["resources"][r]["capacity"] >= quantity]
            choices.sort(key=lambda r: (not r["available"], r["id"] != old.get("vehicle_id"), r["id"]))
            if not choices:
                raise Infeasible(f"{group['id']}没有能承载{quantity:g}的车辆；需另行确认拆批")
            group["vehicle_id"] = choices[0]["id"]
        group["load_units"] = quantity
        groups.append(group)
    return groups


def route_constraints(plan: dict, routes: list) -> tuple[dict, dict, dict]:
    extra, resources, legs = defaultdict(list), {}, {}
    task_map = {t["id"]: t for t in plan["tasks"]}
    previous_trip = {}
    for route in routes:
        vehicle = route["vehicle_id"]
        load = route["loading_task"]
        if vehicle in previous_trip:
            extra[load].append(previous_trip[vehicle])
        resources[load] = vehicle
        prev, node = load, route["depot"]
        for tid in route["stops"]:
            extra[tid].append(prev)
            resources[tid] = vehicle
            legs[tid] = (node, task_map[tid]["to_node"])
            prev, node = tid, task_map[tid]["to_node"]
        ret = route["return_task"]
        resources[ret] = vehicle
        extra[ret].append(prev)
        legs[ret] = (node, route.get("end_depot", route["depot"]))
        previous_trip[vehicle] = ret
    return extra, resources, legs


def production_rank(state: dict, now: float, policy: str) -> dict:
    tasks = [t for t in state["plan"]["tasks"] if t["kind"] == "production" and state["tasks"][t["id"]]["status"] not in {"completed", "running"}]
    if policy != "ts" or not tasks:
        return {}
    from metaforge.problems.jobshop import Task, Job, JobShopProblem
    from metaforge.solvers.tabu_search import TabuSearchSolver
    mids = {r["id"]: i for i, r in enumerate(state["plan"]["resources"]) if r["kind"] == "production"}
    grouped = defaultdict(list)
    for t in tasks:
        grouped[t.get("production_job_id", t["order_id"])].append(t)
    jobs, ids = [], []
    orders = {o["id"]: o for o in state["plan"]["orders"]}
    for oid, pending in sorted(grouped.items()):
        ordered = []
        while pending:
            ready = [t for t in pending if all(d not in {x["id"] for x in pending} for d in t.get("predecessors", []))]
            if not ready:
                raise Infeasible("生产前置关系存在环")
            for t in ready:
                ordered.append(t)
                pending.remove(t)
        jt = []
        for t in ordered:
            # Shared APS metrics use hours (including tariff intervals); execution uses seconds.
            durations = {mids[a["resource_id"]]: sum(timing(t, a["resource_id"], state["tasks"][t["id"]])) / 3600 for a in t["alternatives"]}
            preferred = next(iter(durations))
            jt.append(Task(preferred, durations[preferred], machine_options=list(durations), duration_by_machine=durations))
        order = orders[ordered[0]["order_id"]]
        due = ordered[0].get('source_due_at') or order.get('due_at')
        jobs.append(Job(jt, due_date=(due - now) / 3600 if due is not None else 1e12, priority=ordered[0].get('source_priority', order.get("priority", 1))))
        ids.append([t["id"] for t in ordered])
    random.seed(20261110)
    problem = JobShopProblem(jobs)
    sequence = TabuSearchSolver(problem, max_iterations=40, neighbors_sample=12).run(weights={"makespan": 0.2, "weighted_tardiness_total": 1.0, 'energy_cost': 0, 'machine_busy_cv': 0}, time_limit=2.0)["best_solution"]
    cursor = [0] * len(ids)
    ranking = {}
    for index, j in enumerate(sequence):
        ranking[ids[j][cursor[j]]] = index
        cursor[j] += 1
    return ranking


def metrics(state: dict, slots: list) -> dict:
    by_id = {s["task_id"]: s for s in slots}
    finishes, delays, incomplete = {}, [], set()
    for t in state["plan"]["tasks"]:
        if t["kind"] == "delivery":
            progress = state["tasks"][t["id"]]
            end = progress.get("actual_end_at") if progress["status"] == "completed" else (by_id.get(t["id"]) or {}).get("end_at")
            if end is not None:
                finishes[t["order_id"]] = max(finishes.get(t["order_id"], 0), end)
            else:
                incomplete.add(t["order_id"])
    total, weighted = 0.0, 0.0
    for o in state["plan"]["orders"]:
        if o.get('role') == 'component':
            continue
        if o.get('fulfillment_stage') == 'production':
            ends = [(state['tasks'][tid].get('actual_end_at') if state['tasks'][tid]['status'] == 'completed' else by_id.get(tid, {}).get('end_at')) for tid in o['completion_task_ids']]
            end = max(ends) if ends and all(x is not None for x in ends) else None
        else:
            end = None if o["id"] in incomplete else finishes.get(o["id"])
        late = max(0, end - o["due_at"]) if end is not None and o.get('due_at') is not None else None
        if late is not None:
            total += late
            weighted += late * o.get("priority", 1)
        original_due = state.get("initial_commitments", {}).get(o["id"], {}).get("due_at", o["due_at"])
        delays.append({"order_id": o["id"], "name": o["name"], "due_at": o["due_at"], "original_due_at": original_due, "completion_at": end, "delay_seconds": late})
    old = {s["task_id"]: s for s in state.get("schedule", [])}
    changes = sum(1 for s in slots if s["task_id"] in old and (old[s["task_id"]]["resource_id"] != s["resource_id"] or abs(old[s["task_id"]]["start_at"] - s["start_at"]) > 1))
    window_late, window_penalty = 0.0, 0.0
    for task in state['plan']['tasks']:
        if task.get('window_hard', True) or 'window_end' not in task:
            continue
        progress = state['tasks'][task['id']]
        row = by_id.get(task['id'])
        service_at = progress.get('service_started_at')
        if service_at is None and row:
            service_at = row['end_at'] - task.get('service_seconds', 0)
        if service_at is not None:
            late = max(0, service_at - task['window_end'])
            window_late += late
            window_penalty += late / 60 * task.get('window_late_weight', 1)
    return {"orders": delays, "unknown_orders": sum(d["completion_at"] is None for d in delays), "unknown_commitments": sum(d['due_at'] is None for d in delays), "total_delay_seconds": total, "weighted_delay_seconds": weighted, "changed_tasks": changes,
            "finish_at": max((s["end_at"] for s in slots), default=state["last_tick_at"]), "extra_cost": None,
            "window_lateness_seconds": window_late, "window_penalty_score": window_penalty,
            "cost_note": "尚未导入完整成本口径，不以零成本宣称经济最优"}


def schedule(state: dict, now: float, policy: str = "original", *, rank: dict | None = None, routes: list | None = None, preferences: dict | None = None, assembly_policy: str | None = None) -> dict:
    plan = state["plan"]
    tasks = {t["id"]: t for t in plan["tasks"]}
    dues = {o["id"]: o.get("due_at") or float('inf') for o in plan["orders"]}
    old = {s["task_id"]: s for s in state.get("schedule", [])}
    scope = choose_scope(state, now)
    frozen = {tid: copy.deepcopy(row) for tid, row in old.items()
              if policy != "original" and row["start_at"] >= scope["to_at"] and state["tasks"][tid]["status"] == "pending"}
    routes = copy.deepcopy(routes if routes is not None else route_configuration(state, policy))
    previous_routes = {r["id"]: r for r in state.get("routes", [])}
    routes = [copy.deepcopy(previous_routes[r["id"]]) if r["loading_task"] in frozen and r["id"] in previous_routes else r for r in routes]
    extra, route_res, legs = route_constraints(plan, routes)
    rank = rank or {}
    preferences = preferences or {}
    bookings, ledger = defaultdict(list), defaultdict(list)
    for supply in plan["supplies"]:
        if supply["id"] not in state["received_supplies"]:
            ledger[f"{supply['location']}|{supply['material_id']}"].append((max(now, supply["available_at"]), supply["quantity"]))
    done = {tid: p["actual_end_at"] for tid, p in state["tasks"].items() if p["status"] == "completed"}
    pending = {tid for tid, p in state["tasks"].items() if p["status"] != "completed" and tid not in frozen}
    slots, assumptions = [], []
    for tid, row in frozen.items():
        row["horizon_frozen"] = True
        mid = row["resource_id"]
        bookings[mid].append((row["start_at"], row["end_at"]))
        for line in tasks[tid].get("inputs", []):
            ledger[material_key(line, mid)].append((row["start_at"], -float(line["quantity"])))
        for line in tasks[tid].get("outputs", []):
            ledger[material_key(line, mid)].append((row["end_at"], float(line["quantity"])))
        done[tid] = row["end_at"]
        slots.append(row)
    for r in state["resources"].values():
        if not r["available"]:
            assumptions.append({"resource_id": r["id"], "expected_recovery_at": r.get("expected_recovery_at"), "note": "预计恢复不自动改变实际可用状态"})
    while pending:
        ready = [tid for tid in pending if all(d in done for d in tasks[tid].get("predecessors", []) + extra[tid])]
        if not ready:
            raise Infeasible("前置/车辆行程没有可推进任务")
        def priority(tid):
            t = tasks[tid]
            if state["tasks"][tid]["status"] == "running":
                return (-1, 0, tid)
            if policy == "original":
                return (0, old.get(tid, {}).get("start_at", t["release_at"]), list(tasks).index(tid))
            if t["kind"] == "production" and tid in rank:
                return (0, rank[tid], tid)
            if t["kind"] == "assembly" and assembly_policy == "original":
                return (0, old.get(tid, {}).get("start_at", t["release_at"]), tid)
            if t["kind"] == "assembly" and assembly_policy == "spt":
                return (0, min(sum(timing(t, a["resource_id"], state["tasks"][tid])) for a in t["alternatives"]), tid)
            if policy == "spt":
                return (0, min(sum(timing(t, a["resource_id"], state["tasks"][tid])) for a in t["alternatives"]), tid)
            return (0, dues.get(t.get("order_id"), float("inf")), tid)
        tid = min(ready, key=priority)
        t, progress = tasks[tid], state["tasks"][tid]
        earliest = max(now, t["release_at"], max((done[d] + t.get("transfer_seconds", 0) for d in t.get("predecessors", [])), default=now), max((done[d] for d in extra[tid]), default=now))
        if policy == "original" and tid in old:
            earliest = max(earliest, old[tid]["start_at"])
        mids = [a["resource_id"] for a in t["alternatives"]]
        if tid in route_res:
            mids = [route_res[tid]]
        elif policy == "original" and tid in old:
            mids = [old[tid]["resource_id"]]
        if tid in preferences and preferences[tid].get("resource_id") in mids:
            mids = [preferences[tid]["resource_id"]]
        if progress["status"] == "running" or (progress["inputs_consumed"] and not t.get("resumable", False)):
            mids = [progress["resource_id"]]
        candidates, reasons = [], []
        for mid in mids:
            r = state["resources"][mid]
            try:
                setup, work = timing(t, mid, progress)
                if t["kind"] in {"delivery", "return"}:
                    origin, dest = legs[tid]
                    road = plan["travel_seconds"].get(f"{origin}|{dest}")
                    if road is None:
                        raise Infeasible(f"缺少{origin}→{dest}的行驶时间")
                    work = road + t.get("service_seconds", 0)
                    if progress["status"] != "pending":
                        work = progress.get("batch_remaining", work)
                material_time = earliest if progress["inputs_consumed"] else _material_ready(t, mid, earliest, state["inventory"], ledger)
                start = first_slot(r, material_time, setup + work, bookings[mid], now=now)
                if t["kind"] == "delivery" and progress["status"] == "pending":
                    if t.get('latest_start_at') is not None:
                        # A fixed departure may arrive before opening; waiting occupies the vehicle.
                        work += max(0, t.get('window_start', start + road) - start - road)
                    else:
                        start = max(start, t.get("window_start", start) - road)
                    start = first_slot(r, start, setup + work, bookings[mid], now=now)
                end = start + setup + work
                # The slot describes remaining work; an existing departure is an execution fact.
                departure = progress.get('actual_start_at')
                if departure is None:
                    departure = start
                if departure > t.get('latest_start_at', float('inf')) + 1e-7 or end > t.get('latest_end_at', float('inf')) + 1e-7:
                    raise Infeasible(f'{t["name"]}错过固定发运/交接时限，需确认新计划，不能平移原时限')
                window_check = (progress.get('service_started_at') or start + setup + max(0, work - t.get('service_seconds', 0))) if t.get('window_policy') == 'service_start' else end
                if t.get('window_hard', True) and window_check > t.get("window_end", float("inf")) + 1e-7:
                    raise Infeasible(f"{t['name']}无法满足客户硬时间窗")
                pref = preferences.get(tid, {}).get("resource_id", old.get(tid, {}).get("resource_id"))
                candidates.append(((end, mid != pref, mid), {"task_id": tid, "resource_id": mid, "start_at": start, "end_at": end, "setup_seconds": setup, "work_seconds": work, "fixed": progress["status"] == "running"}))
            except Infeasible as exc:
                reasons.append(str(exc))
                continue
        if not candidates:
            detail = '；'.join(dict.fromkeys(reasons))[:400]
            raise Infeasible(f"{t['name']}在已知资源/日历/物料/时窗下无可行安排：{detail}")
        _, row = min(candidates, key=lambda x: x[0])
        row["route_predecessors"] = list(extra[tid])
        mid, start, end = row["resource_id"], row["start_at"], row["end_at"]
        if tid in legs:
            row["from_node"], row["to_node"] = legs[tid]
            row["travel_seconds"] = plan["travel_seconds"][f"{row['from_node']}|{row['to_node']}"]
            row["arrive_at"] = start + row["travel_seconds"]
            row["service_start_at"] = max(row["arrive_at"], t.get("window_start", row["arrive_at"]))
        if t['kind'] == 'transport':
            row['from_node'], row['to_node'] = t['from_node'], t['to_node']
        bookings[mid].append((start, end))
        if not progress["inputs_consumed"]:
            for line in t.get("inputs", []):
                ledger[material_key(line, mid)].append((start, -float(line["quantity"])))
        for line in t.get("outputs", []):
            ledger[material_key(line, mid)].append((end, float(line["quantity"])))
        done[tid] = end
        pending.remove(tid)
        slots.append(row)
    result = {"policy": policy, "assembly_policy": assembly_policy, "rank": rank, "routes": routes, "schedule": slots, "assumptions": assumptions, "generated_at": now,
              "input_version": state["version"], "constraint_version": state["constraint_version"], "scope": scope}
    result["metrics"] = metrics(state, slots)
    return result


def choose_scope(state: dict, now: float) -> dict:
    event = state.get("last_event") or {}
    target = event.get("target_id")
    tasks = state["plan"]["tasks"]
    affected = {t["id"] for t in tasks if t["id"] == target or any(a["resource_id"] == target for a in t["alternatives"])}
    if event.get("type") in {"supply_delay", "supply_quantity", "inventory_count", "travel_change", "order_change"}:
        affected = {t["id"] for t in tasks if state["tasks"][t["id"]]["status"] != "completed"}
    changed = True
    while changed:
        previous = len(affected)
        affected |= {t["id"] for t in tasks if set(t.get("predecessors", [])) & affected}
        changed = len(affected) > previous
    end = max((s["end_at"] for s in state.get("schedule", []) if s["task_id"] in affected), default=now)
    for r in state["resources"].values():
        if r["id"] == target:
            end = max(end, r.get("expected_recovery_at") or now)
    if event.get("type") == "supply_delay":
        supply = next((s for s in state["plan"]["supplies"] if s["id"] == target), None)
        if supply:
            end = max(end, supply["available_at"])
    task = next((t for t in tasks if t["id"] == target), None)
    if task and event.get("type") in {"release_change", "window_change"}:
        end = max(end, task.get("release_at", now), task.get("window_start", now))
    hours = max(0, (end - now) / 3600)
    window = next((h for h in [4, 24, 168, 672] if hours <= h), 672)
    return {"hours": window, "from_at": now, "to_at": now + window * 3600, "affected_tasks": sorted(affected), "capacity_request": hours > 168,
            "note": "4周层仅提供能力缺口与调整请求，不宣称完成整月联合优化" if window == 672 else "按依赖与交付影响选择滚动窗口"}
