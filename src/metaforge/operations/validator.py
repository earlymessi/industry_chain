"""Independent schedule checks: never trust a solver's score or feasible flag."""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from .models import material_key, timing


def validate(state: dict, candidate: dict, now: float) -> dict:
    checks = []
    def check(code, ok, target, message, actual=None, expected=None):
        checks.append({"code": code, "status": "passed" if ok is True else "unverified" if ok is None else "violated",
                       "target": target, "message": message, "actual": actual, "expected": expected})
    tasks = {t["id"]: t for t in state["plan"]["tasks"]}
    required = {tid for tid, p in state["tasks"].items() if p["status"] != "completed"}
    slots = candidate.get("schedule", [])
    counts = Counter(s.get("task_id") for s in slots)
    check("coverage", set(counts) == required and all(n == 1 for n in counts.values()), "plan", "剩余任务恰好安排一次，无漏排/重复/无来源任务")
    if set(counts) != required or any(n != 1 for n in counts.values()):
        return _result(checks)
    rows = {s["task_id"]: s for s in slots}
    from .coordinator import choose_scope
    horizon = choose_scope(state, now)["to_at"]
    if candidate.get("policy") != "original":
        for old in state.get("schedule", []):
            tid = old["task_id"]
            if tid in rows and old["start_at"] >= horizon and state["tasks"][tid]["status"] == "pending":
                row = rows[tid]
                check("horizon_freeze", all(row.get(k) == old.get(k) for k in ("resource_id", "start_at", "end_at")), tid, "滚动窗口外未开工安排保持，冲突须扩大窗口后重算")
    resources = state["resources"]
    bookings, movements = defaultdict(list), defaultdict(list)
    for supply in state["plan"]["supplies"]:
        if supply["id"] not in state["received_supplies"]:
            movements[f"{supply['location']}|{supply['material_id']}"].append((max(now, supply["available_at"]), supply["quantity"]))
    routes = candidate.get("routes", [])
    route_ids = [r.get("id") for r in routes]
    expected_routes = {r["id"] for r in state["plan"]["route_groups"]}
    check("route_coverage", set(route_ids) == expected_routes and len(route_ids) == len(set(route_ids)), "routes", "每个已确认运输批次有且仅有一条路线")
    extra, route_vehicle, legs = defaultdict(list), {}, {}
    previous_return = {}
    canonical_groups = {r["id"]: r for r in state["plan"]["route_groups"]}
    for route in routes:
        source = canonical_groups.get(route.get("id"))
        if not source:
            check("route_source", False, route.get("id"), "路线来源不存在")
            continue
        rid = route.get("vehicle_id")
        valid = rid in source["vehicle_options"] and rid in resources
        check("vehicle", valid, route["id"], "车辆须来自已确认可用车型/能力集合")
        stops = route.get("stops", [])
        check("stops", Counter(stops) == Counter(source["delivery_tasks"]), route["id"], "客户任务不得遗漏、重复或跨批次偷换")
        old_route = next((r for r in state.get("routes", []) if r["id"] == route["id"]), {})
        frozen = [tid for tid in old_route.get("stops", source["delivery_tasks"]) if state["tasks"][tid]["status"] in {"completed", "running"}]
        check("frozen_visits", stops[:len(frozen)] == frozen, route["id"], "已完成和正在行驶的访问前缀不可重排")
        if not valid or Counter(stops) != Counter(source["delivery_tasks"]):
            continue
        quantity = sum(tasks[t].get("load_units", tasks[t]["quantity"]) for t in stops)
        check("capacity", quantity <= resources[rid]["capacity"] + 1e-7, route["id"], "整批装载不超过额定容量", quantity, resources[rid]["capacity"])
        load = source["loading_task"]
        if rid in previous_return:
            extra[load].append(previous_return[rid])
        progress = state["tasks"][load]
        if progress["status"] != "pending":
            check("loaded_vehicle", rid == progress["resource_id"], load, "已经装载/在途不得凭空换车")
        route_vehicle[load] = rid
        prev, node = load, source["depot"]
        for tid in stops:
            route_vehicle[tid] = rid
            extra[tid].append(prev)
            legs[tid] = (node, tasks[tid]["to_node"])
            prev, node = tid, tasks[tid]["to_node"]
        ret = source["return_task"]
        route_vehicle[ret] = rid
        extra[ret].append(prev)
        legs[ret] = (node, source.get("end_depot", source["depot"]))
        previous_return[rid] = ret
    def end_at(tid):
        p = state["tasks"].get(tid)
        return p.get("actual_end_at") if p and p["status"] == "completed" else rows.get(tid, {}).get("end_at")
    for tid, row in rows.items():
        t, progress = tasks[tid], state["tasks"][tid]
        rid = row.get("resource_id")
        eligible = rid in {a["resource_id"] for a in t["alternatives"]} and rid in resources
        check("capability", eligible, tid, "工序资源能力匹配")
        if not eligible:
            continue
        r = resources[rid]
        start, end = row.get("start_at"), row.get("end_at")
        valid_time = isinstance(start, (float, int)) and isinstance(end, (float, int)) and math.isfinite(start) and math.isfinite(end) and end >= start
        check("time", valid_time, tid, "起止为有限时刻且结束不早于开始")
        if not valid_time:
            continue
        check("future", start >= now - 1e-5, tid, "不下发已过开始时刻的未来动作", start, now)
        check("release", start >= t["release_at"] - 1e-5, tid, "满足任务最早释放")
        check('fixed_deadline', start <= t.get('latest_start_at', float('inf')) + 1e-5 and end <= t.get('latest_end_at', float('inf')) + 1e-5,
              tid, '固定发运/交接时限保持，不随上游延期自动后移')
        if not r["available"]:
            expected = r.get("expected_recovery_at")
            check("recovery_assumption", expected is not None and expected > now and start >= expected - 1e-5, tid, "实际不可用资源仅可按有效恢复估计推演，不能实际提前开工", start, expected)
        check("calendar", any(start >= a - 1e-5 and end <= b + 1e-5 for a, b in r["working_windows"]), tid, "完整加工段处于可用日历内")
        if progress["status"] == "running":
            check("frozen_resource", progress["resource_id"] == rid, tid, "正在执行的任务保持实际资源")
        if progress["inputs_consumed"] and not t.get("resumable", False):
            check("resume_policy", progress["resource_id"] == rid, tid, "不允许转机的在制保持资源")
        for dep in t.get("predecessors", []):
            d = end_at(dep)
            check("precedence", d is not None and start >= d + t.get("transfer_seconds", 0) - 1e-5, tid, f"前置{dep}完成且计入必要转运", start, None if d is None else d + t.get("transfer_seconds", 0))
        for dep in extra[tid]:
            d = end_at(dep)
            check("route_chain", d is not None and start >= d - 1e-5, tid, f"车辆须先完成{dep}")
        setup, work = timing(t, rid, progress)
        if t["kind"] in {"delivery", "return"}:
            check("route_assignment", route_vehicle.get(tid) == rid, tid, "任务与路线车辆一致")
            origin_dest = legs.get(tid)
            if origin_dest is None:
                check("road", None, tid, "缺少完整路线，不能验证")
                continue
            origin, dest = origin_dest
            check("route_nodes", row.get("from_node") == origin and row.get("to_node") == dest, tid, "路线节点与实际访问链一致，不能瞬移")
            road = state["plan"]["travel_seconds"].get(f"{origin}|{dest}")
            check("road", road is not None, tid, "路段时间有来源")
            if road is None:
                continue
            if progress["status"] != "pending":
                work = progress.get("batch_remaining", road + t.get("service_seconds", 0))
            else:
                work = road + t.get("service_seconds", 0)
                arrival = start + road
                service_start = max(arrival, t.get("window_start", arrival))
                work += service_start - arrival
            window_value = (progress.get('service_started_at') or start + setup + max(0, work - t.get('service_seconds', 0))) if t.get('window_policy') == 'service_start' else end
            if t.get('window_hard', True):
                check("hard_window", window_value <= t.get("window_end", float("inf")) + 1e-5, tid, "客户硬收货窗口满足（按来源的开始服务/完成口径）")
            else:
                late = max(0, window_value - t.get('window_end', float('inf')))
                check('soft_window', t.get('window_late_weight', 1) >= 0, tid, f'原物流软窗允许执行，迟到{late / 60:.2f}分钟计入指标', late, '按来源软窗惩罚')
        check("duration", abs(end - start - setup - work) <= 1e-4, tid, "有效剩余工时/行驶服务时间无缩短", end - start, setup + work)
        if tid in route_vehicle:
            check("vehicle_assignment", route_vehicle[tid] == rid, tid, "装载、配送、返场使用同一有效车辆")
        bookings[rid].append((start, end, tid))
        if not progress["inputs_consumed"]:
            for line in t.get("inputs", []):
                movements[material_key(line, rid)].append((start, -float(line["quantity"])))
        for line in t.get("outputs", []):
            movements[material_key(line, rid)].append((end, float(line["quantity"])))
    for rid, intervals in bookings.items():
        intervals.sort()
        for left, right in zip(intervals, intervals[1:]):
            check("exclusive", left[1] <= right[0] + 1e-5, rid, f"{left[2]}与{right[2]}不重叠")
    for key, events in movements.items():
        qty = state["inventory"].get(key, 0)
        grouped = defaultdict(float)
        for at, delta in events:
            grouped[at] += delta
        for at in sorted(grouped):
            qty += grouped[at]
            check("inventory", qty >= -1e-6, key, "逐时供给扣除消耗不为负，物料不重复分配", qty, 0)
    return _result(checks)


def _result(checks):
    violations = [c for c in checks if c["status"] != "passed"]
    return {"status": "passed" if not violations else "unverified" if any(c["status"] == "unverified" for c in violations) else "violated",
            "passed": not violations, "checks": checks, "violations": violations, "checked_count": len(checks)}
