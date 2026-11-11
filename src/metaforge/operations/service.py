from __future__ import annotations

import asyncio
import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from .models import new_state, public_state, timestamp, iso, PARAMETERS
from .plans import prepare_standard, normalize_plan
from .coordinator import schedule, metrics
from .runtime import advance, apply_event
from .validator import validate
from .store import Conflict, FencedOut


def compute_in_process(snapshot, now, timeout):
    """Run a killable child; its output never writes execution state."""
    env = os.environ.copy()
    src = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-m", "metaforge.operations.solve_worker"], input=json.dumps({"snapshot": snapshot, "now": now, "budget": max(1, timeout - 5)}, allow_nan=False),
                            capture_output=True, text=True, encoding="utf-8", env=env, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr[-1000:] or "独立求解进程失败")
    decoded = json.loads(result.stdout)
    if decoded.get("error"):
        raise ValueError(decoded["error"])
    return decoded


class OperationsService:
    def __init__(self, store, *, clock=time.time, tick_seconds=1.0, solver=compute_in_process, enabled=None):
        self.store, self.clock, self.tick_seconds, self.solver = store, clock, tick_seconds, solver
        self.enabled = enabled if enabled is not None else os.getenv("OPERATIONS_ENABLED", "1").lower() not in {"0", "false", "off"}
        self.owner = uuid4().hex
        self.health = {"status": "starting", "error": None}
        self._runner = None
        self._stop = asyncio.Event()
        self._solving = set()
        self._job_tasks = set()
        self._recovered_epoch = None

    async def start(self):
        await self.store.setup()
        if not self.enabled:
            self.health.update(status="disabled", error="运维执行服务已停用，历史状态保留")
            return
        self._runner = asyncio.create_task(self._loop())

    async def stop(self):
        self._stop.set()
        if self._runner:
            await self._runner
        if self._job_tasks:
            await asyncio.gather(*self._job_tasks, return_exceptions=True)

    async def _loop(self):
        while not self._stop.is_set():
            try:
                await self.step()
            except Exception as exc:
                self.health.update(status="error", error=str(exc))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.tick_seconds)
            except asyncio.TimeoutError:
                pass

    async def step(self):
        now = self.clock()
        claim = await self.store.claim(self.owner, now)
        if not claim:
            self.health.update(status="follower", error=None)
            return
        state, head = await self.store.read()
        await self.store.finalize(head)
        if self._recovered_epoch != head["epoch"]:
            await self.store.recover_jobs(self.owner)
            self._recovered_epoch = head["epoch"]
        for command in await self.store.queued(now):
            if command["kind"] == "event" and command["payload"].get("scheduled_at") and timestamp(command["payload"]["scheduled_at"]) > self.clock():
                continue
            receipt = next((r for r in head.get("receipts", []) if r["id"] == command["_id"]), None)
            if receipt:
                await self.store.finalize(head)
                continue
            try:
                state, head = await self._execute(command, state, head)
            except FencedOut:
                self.health.update(status="follower", error="执行维护权已转移，命令由当前维护者继续处理")
                return
            except Conflict as exc:
                await self.store.fail(command["_id"], exc, 409)
            except (ValueError, KeyError, TypeError) as exc:
                await self.store.fail(command["_id"], exc, 422)
        now = self.clock()
        if state:
            updated, transitions = advance(state, now)
            if transitions or now - state["last_tick_at"] >= 5:
                self._forecast(updated, now)
                state, head = await self.store.publish(updated, head, now, logs=transitions)
        if not self._solving:
            for job in await self.store.pending_jobs():
                self._solving.add(job["_id"])
                task = asyncio.create_task(self._solve(job))
                self._job_tasks.add(task)
                task.add_done_callback(self._job_tasks.discard)
                break
        self.health.update(status="online", error=None, checked_at=now)

    async def _execute(self, command, state, head):
        now = self.clock()
        body = command["payload"]
        logs = []
        if command["kind"] == "activate":
            if body.get('source') == 'chain':
                if not getattr(self, 'chain_loader', None):
                    raise Conflict('计划衔接读取器未配置')
                body = {**body, 'plan': await self.chain_loader(body.get('preview_id'), state)}
            replace_legacy = bool(state and state['plan']['id'] == 'REFRIGERATOR-STANDARD-v1' and body.get('replace_legacy') and body.get('previous_run_id') == state['run_id'] and body['plan'].get('alignment_version') == 2)
            switch_source = bool(state and body.get('confirm_new_run') and body.get('source') in {'production', 'chain'} and body.get('previous_run_id') == state['run_id'])
            if state and not replace_legacy and not switch_source and not (state["status"] == "idle" and body.get("archive_previous") and body.get("previous_run_id") == state["run_id"]):
                raise Conflict("已有持续运行实例；不允许刷新或重复初始化覆盖当前现场")
            previous_state = state
            plan = normalize_plan(body["plan"])
            if plan["start_at"] < now - 2 and not body.get("allow_history_replay"):
                raise ValueError("计划起点已过，请重新选起点或明确确认标准模拟历史回放")
            state = new_state(plan, min(now, plan["start_at"]))
            initial = self.initial_candidate(state, plan['start_at'])
            report = validate(state, initial, plan["start_at"])
            if not report["passed"]:
                raise ValueError("计划未通过独立校验：" + str(report["violations"][:2]))
            if previous_state:
                archived, archive_transitions = advance(previous_state, now)
                archived['archived_at'] = now
                archived['archive_transitions'] = archive_transitions
                archived['archive_reason'] = '旧独立算例替换为原系统对齐基线，旧事件不冒充真实设备反馈' if replace_legacy else '用户确认启用新计划，原进度与事件归档' if switch_source else '运行完成归档'
                await self.store.archive(archived)
                logs.append({'type': 'legacy_baseline_archived' if replace_legacy else 'previous_run_archived', 'occurred_at': now,
                             'target_id': previous_state['run_id'], 'source': 'operator', 'reason': archived['archive_reason']})
            state["schedule"], state["routes"] = initial["schedule"], initial["routes"]
            state["plan"]["schedule"] = copy.deepcopy(initial["schedule"])
            state, log = advance(state, now)
            logs += log
            logs.append({"type": "plan_activated", "occurred_at": now, "source": plan["source"], "target_id": plan["id"], "operator": body.get("operator", "operator")})
            result = {"run_id": state["run_id"], "message": "已启用计划，时钟读取服务器当前时间"}
        else:
            if not state or body.get("run_id") != state["run_id"]:
                raise Conflict("当前运行实例已变化")
            if command["kind"] == "event":
                event = {**body, "id": command["_id"], "occurred_at": body.get("occurred_at") or body.get("scheduled_at") or command["created_at"], "received_at": command["created_at"]}
                if timestamp(event["occurred_at"]) > now + 2:
                    raise ValueError("即时事件发生时间不能晚于当前时间；预约事件请使用计划事件")
                state, logs = apply_event(state, event, now)
                logs.append({"type": event["type"], "target_id": event.get("target_id"), "occurred_at": timestamp(event["occurred_at"]), "received_at": command["created_at"], "applied_at": now,
                             "source": event.get("source", "manual_simulation"), "operator": event.get("operator", "operator"), "data": event.get("data"), "reason": event.get("reason", "")})
                result = {"event_id": command["_id"], "run_id": state["run_id"], "message": "事件已生效，主时钟与无关任务继续"}
            elif command['kind'] == 'sync_production':
                from .production_sync import synchronize, NewRunRequired
                preview = await self.store.get_preview(body['preview_id'])
                if not preview or preview['run_id'] != state['run_id'] or preview['constraint_version'] != state['constraint_version']:
                    raise Conflict('预览后运行条件已变化，请重新预览生产同步')
                if preview.get('expires_at', 0) < now:
                    raise Conflict('同步预览已过期，请重新预览')
                if not getattr(self, 'production_loader', None):
                    raise Conflict('生产来源读取器未配置')
                request = {**preview['request'], 'source_version': preview['source_version']}
                native = await self.production_loader(request, preview['anchor_at'])
                try:
                    state, summary, transitions = synchronize(state, native, self.clock())
                except NewRunRequired as exc:
                    raise Conflict(str(exc))
                now = self.clock()
                logs += transitions
                logs.append({'type': 'production_source_synced', 'occurred_at': now, 'target_id': native['source_plan_id'],
                             'source': 'production', 'operator': body.get('operator', 'operator'), 'summary': summary})
                result = {'run_id': state['run_id'], 'message': '库内生产计划已同步，已执行进度与本地确认修改保留', 'summary': summary}
            elif command["kind"] == "apply":
                job = await self.store.job(body["job_id"])
                if not job or job["run_id"] != state["run_id"] or job["status"] != "done":
                    raise Conflict("候选不存在、尚未完成或属于其他实例")
                if job.get("applied_command_id") and job["applied_command_id"] != command["_id"]:
                    raise Conflict("该次候选已经应用，请重新评估")
                c = next((c for c in job["result"]["candidates"] if c["id"] == body["candidate_id"]), None)
                if not c:
                    raise ValueError("请选择本次返回的具体候选")
                if c["constraint_version"] != state["constraint_version"]:
                    raise Conflict("求解后有新的关键变化，请基于最新状态重新计算")
                state, logs = advance(state, now)
                preferences = {s["task_id"]: s for s in c["schedule"]}
                snapshot = job["snapshot"]
                for tid, progress in state["tasks"].items():
                    original = snapshot["tasks"][tid]
                    if progress["status"] in {"running", "completed"} and original["status"] not in {"running", "completed"}:
                        if tid in preferences and preferences[tid]["resource_id"] != progress["resource_id"]:
                            raise Conflict(f"{tid}已在新资源上开工，原候选不能覆盖实际事实")
                updated = schedule(state, now, c["policy"], rank=c["rank"], routes=c["routes"], preferences=preferences, assembly_policy=c.get("assembly_policy"))
                report = validate(state, updated, now)
                if not report["passed"]:
                    raise Conflict("候选接回时未通过最新约束：" + str(report["violations"][:2]))
                state["schedule"], state["routes"] = updated["schedule"], updated["routes"]
                state["plan_revision"] += 1
                state["constraint_version"] += 1
                state["last_adjustment"] = {"job_id": body["job_id"], "candidate_id": c["id"], "applied_at": now, "validation": report, "metrics": updated["metrics"]}
                logs.append({"type": "adjustment_applied", "occurred_at": now, "target_id": body["job_id"], "candidate_id": c["id"], "source": "operator", "operator": body.get("operator", "operator"), "metrics": updated["metrics"]})
                result = {"job_id": body["job_id"], "candidate_id": c["id"], "run_id": state["run_id"], "message": "已按当前时刻重校验并发布未来差异"}
            else:
                raise ValueError("未知执行命令")
        self._forecast(state, now)
        state, head = await self.store.publish(state, head, now, command_id=command["_id"], result=result, logs=logs)
        if command["kind"] == "apply":
            await self.store.update_job(body["job_id"], {"applied_command_id": command["_id"], "applied_at": now})
        return state, head

    def _forecast(self, state, now):
        try:
            forecast = schedule(state, now, "original", routes=state["routes"])
            report = validate(state, forecast, now)
            if not report["passed"]:
                raise ValueError(str(report["violations"][:1]))
            state["forecast"] = {"status": "available", "at": now, "schedule": forecast["schedule"], "assumptions": forecast["assumptions"]}
            state["metrics"] = forecast["metrics"]
        except (ValueError, KeyError) as exc:
            state["forecast"] = {"status": "unresolved", "at": now, "message": str(exc), "schedule": []}
            state["metrics"] = metrics(state, [])

    async def current(self):
        state, head = await self.store.read()
        now = self.clock()
        health = {**self.health, "heartbeat_at": (head or {}).get("heartbeat_at"), "lease_until": (head or {}).get("lease_until")}
        if self.enabled and head and head.get("lease_until", 0) <= now:
            health["status"] = "offline"
        return public_state(state, now, health)

    async def submit(self, kind, body, command_id=None):
        if not self.enabled:
            raise Conflict("运维服务已停用，不能提交执行命令")
        cid = command_id or uuid4().hex
        await self.store.submit(cid, kind, body, self.clock())
        return cid

    async def await_command(self, cid, seconds=4):
        until = time.monotonic() + seconds
        while True:
            doc = await self.store.command(cid)
            if not doc or doc["status"] != "queued" or time.monotonic() >= until:
                return doc
            await asyncio.sleep(0.05)

    async def preview(self, raw=None, start_at=None):
        now = self.clock()
        plan = normalize_plan(raw if raw is not None else prepare_standard(timestamp(start_at) if start_at else now + 30))
        state = new_state(plan, min(now, plan["start_at"]))
        c = self.initial_candidate(state, plan['start_at'])
        report = validate(state, c, plan["start_at"])
        return {"plan": plan, "candidate": c, "validation": report, "can_activate": report["passed"], "message": "主时钟读取当前时间；首次生效日期固定，刷新不平移计划"}

    @staticmethod
    def initial_candidate(state, now):
        if state['plan'].get('schedule'):
            return {'schedule': copy.deepcopy(state['plan']['schedule']), 'routes': copy.deepcopy(state['plan']['routes']),
                    'policy': 'original', 'metrics': metrics(state, state['plan']['schedule']), 'assumptions': []}
        return schedule(state, now)

    async def request_adjustment(self, run_id, jid=None):
        if not self.enabled:
            raise Conflict("运维服务已停用，不能创建调整任务")
        state, _ = await self.store.read()
        if not state or state["run_id"] != run_id:
            raise Conflict("运行实例不存在或已变化")
        if jid:
            existing = await self.store.job(jid)
            if existing:
                if existing["run_id"] != run_id:
                    raise Conflict("同一请求ID不能跨运行实例使用")
                return existing
        now = self.clock()
        snapshot, _ = advance(state, now)
        job = {"_id": jid or uuid4().hex, "run_id": run_id, "created_at": now, "status": "queued", "snapshot": snapshot, "snapshot_at": now}
        return await self.store.put_job(job)

    async def _solve(self, job):
        jid = job["_id"]
        try:
            await self.store.update_job(jid, {"status": "running", "owner": self.owner, "started_at": self.clock()})
            timeout = max(5, min(60, float(os.getenv("OPERATIONS_SOLVER_TIMEOUT", "30"))))
            result = await asyncio.to_thread(self.solver, job["snapshot"], job["snapshot_at"], timeout)
            await self.store.update_job(jid, {"status": "done", "result": result, "finished_at": self.clock()})
        except Exception as exc:
            await self.store.update_job(jid, {"status": "failed", "error": str(exc), "finished_at": self.clock()})
        finally:
            self._solving.discard(jid)
