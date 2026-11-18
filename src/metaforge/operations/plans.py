from __future__ import annotations

import copy
import json
from pathlib import Path
from datetime import datetime, timezone

from .models import timestamp, number

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "operations" / "standard"


def prepare_standard(start_at: float) -> dict:
    from .sources import aligned_standard
    return aligned_standard(start_at)


def normalize_plan(raw: dict) -> dict:
    plan = copy.deepcopy(raw)
    for field in ("id", "name", "source", "orders", "resources", "tasks", "stock", "supplies", "travel_seconds", "routes"):
        if field not in plan:
            raise ValueError(f"计划缺少{field}")
    if plan.get("mode", "simulation") != "simulation":
        raise ValueError("首版激活仅支持明确标记的模拟执行；现场模式需完成反馈适配")
    plan["mode"] = "simulation"
    plan["start_at"] = timestamp(plan["start_at"])
    if not 0 < len(plan["tasks"]) <= 3000:
        raise ValueError("计划任务数须为1至3000")
    def unique(items, label):
        ids = [str(x["id"]) for x in items]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{label}ID重复")
        for x in items:
            if not isinstance(x["id"], str) or not x["id"]:
                raise ValueError(f"{label}须使用非空字符串ID")
        return set(ids)
    resources = unique(plan["resources"], "资源")
    orders = unique(plan["orders"], "订单")
    tasks = unique(plan["tasks"], "任务")
    unique(plan["supplies"], "供给")
    for r in plan["resources"]:
        r["capacity"] = number(r.get("capacity", 1), "容量", 0.000001)
        r["working_windows"] = [[timestamp(a), timestamp(b)] for a, b in r.get("working_windows", [])]
        if not r["working_windows"] or any(b <= a for a, b in r["working_windows"]):
            raise ValueError(f"{r['id']}缺少有效可用时间窗")
    for o in plan["orders"]:
        o["due_at"] = timestamp(o["due_at"]) if o.get("due_at") is not None else None
        o["quantity"] = number(o["quantity"], "订单数量", 0.000001)
        o["priority"] = number(o.get("priority", 1), "优先级", 0.000001)
    for t in plan["tasks"]:
        if t["kind"] not in {"production", "assembly", "transport", "loading", "delivery", "return"}:
            raise ValueError("未知任务类型")
        if t.get("order_id") and t["order_id"] not in orders:
            raise ValueError("任务引用不存在的订单")
        if any(p not in tasks for p in t.get("predecessors", [])):
            raise ValueError("工序前置引用不存在")
        t["quantity"] = number(t.get("quantity", 1), "任务数量", 0.000001)
        t["release_at"] = timestamp(t.get("release_at", plan["start_at"]))
        t["duration_mode"] = t.get("duration_mode", "batch")
        if t["duration_mode"] not in {"batch", "per_unit"}:
            raise ValueError("工时口径只支持单件或整批")
        if not t["alternatives"]:
            raise ValueError("任务缺少可执行资源")
        for alt in t["alternatives"]:
            if alt["resource_id"] not in resources:
                raise ValueError("候选资源不存在")
            alt["setup_seconds"] = number(alt.get("setup_seconds", 0), "准备时间")
            field = "unit_seconds" if t["duration_mode"] == "per_unit" else "duration_seconds"
            alt[field] = number(alt.get(field, 0), "有效工时", 0 if t["kind"] in {"delivery", "return"} else 0.000001)
            resource = next(r for r in plan["resources"] if r["id"] == alt["resource_id"])
            expected_kind = "vehicle" if t["kind"] in {"transport", "loading", "delivery", "return"} else t["kind"]
            if resource["kind"] != expected_kind:
                raise ValueError("工序与资源业务类型不匹配")
        for key in ("inputs", "outputs"):
            for line in t.get(key, []):
                line["quantity"] = number(line["quantity"], "物料数量", 0.000001)
        for field in ("transfer_seconds", "transfer_on_reassign_seconds", "service_seconds", "load_units", "window_late_weight"):
            if field in t:
                t[field] = number(t[field], field)
        if 'window_hard' in t and not isinstance(t['window_hard'], bool):
            raise ValueError('窗口硬约束标识必须为布尔值')
        if t.get('window_policy', 'finish') not in {'finish', 'service_start'}:
            raise ValueError('未知客户窗口口径')
        for key in ("window_start", "window_end", "latest_start_at", "latest_end_at"):
            if key in t:
                t[key] = timestamp(t[key])
        if t.get("window_end", float("inf")) < t.get("window_start", -float("inf")):
            raise ValueError("收货时间窗结束早于开始")
    # A cycle is a data error, not an empty/zero-duration schedule.
    pending = {t["id"]: set(t.get("predecessors", [])) for t in plan["tasks"]}
    while pending:
        ready = {k for k, v in pending.items() if not v}
        if not ready:
            raise ValueError("任务前置存在环")
        pending = {k: v - ready for k, v in pending.items() if k not in ready}
    keys = [(x["location"], x["material_id"]) for x in plan["stock"]]
    if len(keys) != len(set(keys)):
        raise ValueError("初始库存库位/物料重复")
    for item in plan["stock"]:
        item["quantity"] = number(item["quantity"], "初始库存")
    for supply in plan["supplies"]:
        supply["available_at"] = timestamp(supply["available_at"])
        supply["quantity"] = number(supply["quantity"], "供给数量")
    for key, value in list(plan["travel_seconds"].items()):
        plan["travel_seconds"][key] = number(value, f"路段{key}时间", 0.000001)
    unique(plan["route_groups"], "运输批次")
    deliveries = []
    task_map = {t["id"]: t for t in plan["tasks"]}
    for group in plan["route_groups"]:
        if not group["delivery_tasks"] or len(set(group["delivery_tasks"])) != len(group["delivery_tasks"]):
            raise ValueError("运输批次须包含不重复配送任务")
        for tid, kind in [(group["loading_task"], "loading"), (group["return_task"], "return")]+[(d, "delivery") for d in group["delivery_tasks"]]:
            if tid not in tasks or task_map[tid]["kind"] != kind:
                raise ValueError("运输任务类型或引用错误")
            if not set(group["vehicle_options"]).issubset({a["resource_id"] for a in task_map[tid]["alternatives"]}):
                raise ValueError("整趟路线须具有一致的候选车辆能力")
        deliveries += group["delivery_tasks"]
    if sorted(deliveries) != sorted(t["id"] for t in plan["tasks"] if t["kind"] == "delivery"):
        raise ValueError("所有配送任务须且仅属于一个运输批次")
    for order in plan["orders"]:
        if order.get("fulfillment_stage") == "production":
            terminals = order.get("completion_task_ids") or []
            if not terminals or any(tid not in tasks or task_map[tid].get("order_id") != order["id"] or task_map[tid]["kind"] in {"delivery", "return"} for tid in terminals):
                raise ValueError("生产完工目标须绑定本工单明确的完成工序")
            continue
        quantity = sum(task_map[d]["quantity"] for d in deliveries if task_map[d].get("order_id") == order["id"])
        if abs(quantity - order["quantity"]) > 1e-6:
            raise ValueError("配送数量须与原订单数量守恒，不能漏交或重复交付")
    for group in plan["route_groups"]:
        def amounts(lines):
            result = {}
            for line in lines:
                key = line["material_id"]
                result[key] = result.get(key, 0) + line["quantity"]
            return result
        load = task_map[group["loading_task"]]
        delivered = amounts([line for d in group["delivery_tasks"] for line in task_map[d].get("inputs", [])])
        if amounts(load.get("inputs", [])) != delivered or amounts(load.get("outputs", [])) != delivered:
            raise ValueError("装车、在途与交付物料数量须一致")
    return plan
