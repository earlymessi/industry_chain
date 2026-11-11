"""Harness-backed operations tools. They never mutate execution state."""
from __future__ import annotations

import re

from metaforge.tools.base import ToolContext, ToolResult, ToolSpec
from metaforge.tools.registry import get_tool, register_tool
from .coordinator import choose_scope


def state_from(ctx):
    state = ctx.extras.get("operations_state")
    if not state:
        raise ValueError("尚无活动产业链运行实例")
    return state


def query(params, ctx):
    state = state_from(ctx)
    return ToolResult(ok=True, data={"run_id": state["run_id"], "version": state["version"], "source": state["source"],
        "unavailable": [r["id"] for r in state["resources"].values() if not r["available"]],
        "running": [tid for tid, p in state["tasks"].items() if p["status"] == "running"],
        "blocked": [{"task_id": tid, "reason": p.get("blocked_reason")} for tid, p in state["tasks"].items() if p.get("blocked_reason")]})


def impact(params, ctx):
    state = state_from(ctx)
    scope = choose_scope(state, ctx.extras["operations_now"])
    order_ids = {t.get("order_id") for t in state["plan"]["tasks"] if t["id"] in scope["affected_tasks"]}
    return ToolResult(ok=True, data={"scope": scope, "orders": [o for o in state["plan"]["orders"] if o["id"] in order_ids],
        "note": "影响按任务依赖与原承诺识别，具体顺序/资源/时间由重排工具生成。"})


def draft(params, ctx):
    state = state_from(ctx)
    message = params["message"]
    entities = [(r["id"], r["name"], "resource") for r in state["resources"].values()]
    entities += [(t["id"], t["name"], "task") for t in state["plan"]["tasks"]]
    entities += [(s["id"], s.get("name", s["id"]), "supply") for s in state["plan"]["supplies"]]
    found = [(i, name, kind) for i, name, kind in entities if i.lower() in message.lower() or name in message]
    found.sort(key=lambda x: len(x[0]), reverse=True)
    if not found:
        return ToolResult(ok=True, data={"draft": None, "missing": ["请选择或说出明确的机台、工位、供给批次或工序ID"], "message": "没有推测目标对象。"})
    target, _, kind = found[0]
    matched = re.search(r"(\d+(?:\.\d+)?)\s*(分钟|小时|秒)", message)
    seconds = float(matched[1]) * {"分钟": 60, "小时": 3600, "秒": 1}[matched[2]] if matched else None
    if kind == "resource":
        expected = any(k in message for k in ["预计", "等待", "尚未", "未恢复", "计划恢复"])
        confirmed = any(k in message for k in ["已恢复", "确认恢复", "修好", "已可用"])
        unavailable = any(k in message for k in ["故障", "缺失", "停用", "不可用", "坏", "未恢复", "等待恢复"])
        if confirmed and not expected and not any(k in message for k in ["不可用", "无法"]):
            event = {"type": "resource_recovered", "target_id": target, "data": {}}
        elif unavailable:
            event = {"type": "resource_unavailable", "target_id": target, "data": {"expected_recovery_at": ctx.extras["operations_now"] + seconds if seconds else None}}
        else:
            return ToolResult(ok=True, data={"draft": None, "missing": ["请明确说明资源故障，或说明已确认恢复；预计恢复不作为实际复机"]})
    elif kind == "task" and seconds and any(k in message for k in ["工时", "加工", "组装", "耗时", "每件", "每台"]):
        task = next(t for t in state["plan"]["tasks"] if t["id"] == target)
        if task["kind"] not in {"production", "assembly"}:
            return ToolResult(ok=True, data={"draft": None, "missing": ["配送/服务时间请使用对应结构化表单"]})
        event = {"type": "duration_change", "target_id": target, "data": {"duration_mode": task["duration_mode"], "value": seconds}}
        resource = next((r for r in state["resources"] if r in message), None)
        if resource:
            event["data"]["resource_id"] = resource
        else:
            return ToolResult(ok=True, data={"draft": None, "missing": ["请指定该工序在哪个资源上的工时变化，或使用表单选择"]})
    elif kind == "supply" and seconds and "延" in message:
        supply = next(s for s in state["plan"]["supplies"] if s["id"] == target)
        event = {"type": "supply_delay", "target_id": target, "data": {"available_at": max(ctx.extras["operations_now"], supply["available_at"]) + seconds}}
    else:
        return ToolResult(ok=True, data={"draft": None, "missing": ["缺少明确的变化类型、时间数值或单位，请补充或用参数表单"]})
    return ToolResult(ok=True, data={"draft": {**event, "reason": message, "source": "manual_simulation", "run_id": state["run_id"]},
        "missing": [], "message": "仅生成草稿，尚未提交。请核对对象、单件/批次口径、数值及单位。"})


def propose(params, ctx):
    state = state_from(ctx)
    return ToolResult(ok=True, data={"request": {"run_id": state["run_id"]}, "message": "调用同一后台求解器生成资源、顺序、时间和路线；不直接发布。"})


def register():
    for name, description, handler, schema in [
        ("operations.query_state", "读取产业链运维当前事实与阻塞", query, {"type": "object", "properties": {}}),
        ("operations.analyze_impact", "根据依赖识别运维影响及滚动窗口", impact, {"type": "object", "properties": {}}),
        ("operations.prepare_event", "从有明确对象和数值的描述生成待核对草稿，不提交", draft, {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}),
        ("operations.propose_adjustment", "构造后台候选求解请求，不发布执行指令", propose, {"type": "object", "properties": {}}),
    ]:
        try:
            get_tool(name)
        except KeyError:
            register_tool(ToolSpec(name=name, description_zh=description, input_schema=schema, output_schema={"type": "object"}, handler=handler, risk_level="allow"))


register()
