"""Harness-backed operations tools. They never mutate execution state."""
from __future__ import annotations

import re

from metaforge.tools.base import ToolContext, ToolResult, ToolSpec
from metaforge.tools.registry import get_tool, register_tool
from .coordinator import choose_scope
from .models import PARAMETERS


def state_from(ctx):
    state = ctx.extras.get("operations_state")
    if not state:
        raise ValueError("尚无活动产业链运行实例")
    return state


def query(params, ctx):
    state = state_from(ctx)
    definitions = {t['id']: t for t in state['plan']['tasks']}
    now = ctx.extras['operations_now']
    forecast = state.get('forecast', {})
    predictions = {r['task_id']: r for r in forecast.get('schedule', [])} if forecast.get('status') == 'available' else {}
    stages = []
    for kind, label in [('production','生产'),('assembly','组装'),('transport','入厂运输'),('loading','装车'),('delivery','配送'),('return','返场')]:
        ids = [tid for tid,t in definitions.items() if t['kind'] == kind]
        rows = [predictions[tid] for tid in ids if tid in predictions]
        stages.append({'kind':kind,'name':label,'total':len(ids),
            'completed':sum(state['tasks'][tid]['status']=='completed' for tid in ids),
            'running':sum(state['tasks'][tid]['status']=='running' for tid in ids),
            'paused':sum(state['tasks'][tid]['status']=='paused' for tid in ids),
            'predicted_start_at':min((r['start_at'] for r in rows),default=None),
            'predicted_end_at':max((r['end_at'] for r in rows),default=None)})
    return ToolResult(ok=True, data={"run_id": state["run_id"], "version": state["version"], "source": state["source"],
        'clock_at':now,'timezone':'Asia/Shanghai','plan_name':state['plan'].get('name'),
        'available_actions':[{'type':p['type'],'label':p['label']} for p in PARAMETERS],
        'paused_details':[{'task_id':tid,'name':definitions[tid]['name'],'resource_id':p['resource_id'],
            'actual_start_at':p['actual_start_at'],'work_seconds':p['work_seconds'],'quantity_remaining':p['quantity_remaining']}
            for tid,p in state['tasks'].items() if p['status']=='paused'],
        'forecast_message':forecast.get('message'),'stages':stages,
        'last_event':{k:v for k,v in (state.get('last_event') or {}).items() if k in {'type','target_id','data','applied_at','reason'}},
        'running_details':[{'task_id':tid,'name':definitions[tid]['name'],'kind':definitions[tid]['kind'],
            'resource_id':p['resource_id'],'actual_start_at':p['actual_start_at'],'work_seconds':p['work_seconds']}
            for tid,p in state['tasks'].items() if p['status']=='running'],
        "constraint_version":state["constraint_version"],"forecast_status":state.get("forecast",{}).get("status","unknown"),
        "metrics":state.get("metrics",{}),"mode":state["plan"].get("mode"),"coverage":state["plan"].get("coverage",{}),
        "unavailable_details":[{"id":r["id"],"name":r["name"],"expected_recovery_at":r.get("expected_recovery_at"),
            "recovery_overdue":r.get("expected_recovery_at") is not None and r["expected_recovery_at"] <= now} for r in state["resources"].values() if not r["available"]],
        "unavailable": [r["id"] for r in state["resources"].values() if not r["available"]],
        "running": [tid for tid, p in state["tasks"].items() if p["status"] == "running"],
        "blocked": [{"task_id": tid, "name":next(t["name"] for t in state["plan"]["tasks"] if t["id"]==tid), "reason": p.get("blocked_reason")} for tid, p in state["tasks"].items() if p.get("blocked_reason")]})


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
    def mentions(text):
        return bool(re.search(r'(?<![A-Za-z0-9_])'+re.escape(str(text))+r'(?![A-Za-z0-9_])',message,re.IGNORECASE))
    found = [(i,name,kind) for i,name,kind in entities if mentions(i) or mentions(name)]
    preferred='task' if any(k in message for k in ('工时','加工时间','组装时间','耗时','每件','每台')) else 'supply' if any(k in message for k in ('延期','延迟','推迟')) else 'resource'
    candidates=[row for row in found if row[2]==preferred] or found
    if len(candidates)>1:
        return ToolResult(ok=True,data={'draft':None,'missing':['匹配到多个对象，请一次指定一个明确的资源、任务或供给批次'],'candidates':[{'id':i,'name':name,'kind':kind} for i,name,kind in candidates]})
    found=candidates
    if not found:
        return ToolResult(ok=True, data={"draft": None, "missing": ["请选择或说出明确的机台、工位、供给批次或工序ID"], "message": "没有推测目标对象。"})
    target, _, kind = found[0]
    matched = re.search(r"(\d+(?:\.\d+)?)\s*(分钟|小时|秒)", message)
    seconds = float(matched[1]) * {"分钟": 60, "小时": 3600, "秒": 1}[matched[2]] if matched else None
    if kind == "resource":
        expected = any(k in message for k in ["预计", "等待", "尚未", "未恢复", "计划恢复"])
        confirmed = any(k in message for k in ["已恢复", "确认恢复", "修好", "已可用"])
        unavailable = any(k in message for k in ["故障", "缺失", "停用", "停机", "检修", "维修中", "不可用", "坏", "未恢复", "等待恢复"])
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
        resource = next((r["id"] for r in state["resources"].values() if mentions(r["id"]) or mentions(r["name"])), None)
        if resource:
            event["data"]["resource_id"] = resource
        else:
            return ToolResult(ok=True, data={"draft": None, "missing": ["请指定该工序在哪个资源上的工时变化，或使用表单选择"]})
    elif kind == "supply" and seconds and any(k in message for k in ("延","推迟")):
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
