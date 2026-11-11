from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from bson import ObjectId
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .models import timestamp
from .plans import prepare_standard
from .service import OperationsService
from .store import MongoStore, Conflict


def install(app, db, assembly_reader=None):
    service = OperationsService(MongoStore(db))
    app.state.operations = service
    app.include_router(create_router(service, db.work_orders, db.machines_layout, db.materials_inventory, allow_implicit_standard=False, assembly_reader=assembly_reader))
    return service


def create_router(service, production_collection=None, machine_collection=None, material_collection=None, standard_factory=prepare_standard, allow_implicit_standard=True, assembly_reader=None, chain_source_root=None):
    router = APIRouter(prefix="/api/operations-tools", tags=["产业链运维系统"])

    async def native_plan(raw, start):
        from .sources import production_plan
        if production_collection is None or machine_collection is None:
            raise ValueError('原生产计划与设备目录未配置')
        try:
            oid = ObjectId(raw.get('plan_id', ''))
        except Exception:
            raise ValueError('请选择有效的原生产计划')
        doc = await production_collection.find_one({'_id': oid})
        if not doc:
            raise ValueError('原生产计划不存在')
        machines = await machine_collection.find().to_list(500)
        materials = await material_collection.find().to_list(500) if material_collection is not None else []
        plan = production_plan(doc, machines, materials, start, solver=raw.get('solver_id'), time_unit=raw.get('time_unit', 'hours'))
        expected = raw.get('source_version')
        if expected and expected != plan['source_manifest'][0]['sha256']:
            raise Conflict('预览后原计划或算法结果已变化，请重新预览')
        return plan

    service.production_loader = native_plan
    from .chain_api import attach
    from .sources import ROOT
    attach(router, service, native_plan, assembly_reader, chain_source_root or ROOT)

    @router.get('/plans/production/status')
    async def production_status():
        from .production_sync import source_link
        from .sources import selected_result, fingerprint
        state, _ = await service.store.read()
        link = source_link(state['plan']) if state else None
        if not link:
            return {'status': 'unbound', 'has_updates': False, 'message': '请选择库内已排程计划作为生产来源'}
        if production_collection is None:
            return {**link, 'status': 'unavailable', 'has_updates': False, 'message': '生产计划库未配置'}
        try:
            doc = await production_collection.find_one({'_id': ObjectId(link['plan_id'])})
            if not doc:
                return {**link, 'status': 'missing', 'has_updates': False, 'message': '来源计划已删除，当前运行保留，请重新选择来源'}
            solver, result = selected_result(doc, link['solver_id'])
            version = fingerprint({'jobs': doc.get('jobs') or [], 'gantt': result.get('gantt_data')})
            changed = version != link.get('source_version')
            return {**link, 'name': doc.get('plan_name', ''), 'status': 'changed' if changed else 'synced',
                    'has_updates': changed, 'latest_version': version, 'solver_id': solver,
                    'message': '库内有新排程，预览后同步' if changed else '已与选定的库内排程版本同步'}
        except (ValueError, TypeError, KeyError) as exc:
            return {**link, 'status': 'unavailable', 'has_updates': False, 'message': str(exc)}

    @router.post('/plans/production/preview-sync')
    async def preview_production_sync(body: dict = Body(...)):
        from .production_sync import source_link, synchronize, NewRunRequired
        state, _ = await service.store.read()
        if not state or body.get('run_id') != state['run_id']:
            raise HTTPException(409, '运行实例已变化，请刷新')
        try:
            link = source_link(state['plan'])
            anchor = timestamp(body['start_at']) if body.get('start_at') else (link or {}).get('anchor_at', state['plan']['start_at'])
            native = await native_plan(body, anchor)
            # The saved source itself must be valid before its future changes can be merged.
            source_check = await service.preview(native)
            if not source_check['can_activate']:
                return {**source_check, 'mode': 'sync', 'requires_new_run': False}
            try:
                merged, summary, _ = synchronize(state, native, service.clock())
            except NewRunRequired as exc:
                native = await native_plan(body, timestamp(body['start_at']) if body.get('start_at') else service.clock() + 30)
                source_check = await service.preview(native)
                return {'mode': 'new_run', 'requires_new_run': True, 'can_activate': source_check['can_activate'], 'message': str(exc),
                        'source_version': native['source_manifest'][0]['sha256'], 'plan': native,
                        'validation': source_check['validation']}
            key = uuid4().hex
            request = {k: body[k] for k in ('plan_id', 'solver_id', 'time_unit') if k in body}
            await service.store.put_preview({'_id': key, 'run_id': state['run_id'], 'constraint_version': state['constraint_version'],
                                             'source_version': native['source_manifest'][0]['sha256'], 'anchor_at': anchor,
                                             'request': request, 'expires_at': service.clock() + 300})
            return {'mode': 'sync', 'preview_id': key, 'can_activate': True, 'requires_new_run': False,
                    'source_version': native['source_manifest'][0]['sha256'], 'summary': summary, 'validation': summary['validation'],
                    'message': '来源无变化，保留当前安排' if summary['unchanged'] else '保留既成事实及本地确认修改，更新未开工任务并校验下游',
                    'plan': merged['plan'], 'schedule': merged['schedule']}
        except (ValueError, KeyError, TypeError) as exc:
            raise mapped_error(exc)

    @router.post('/plans/production/sync')
    async def sync_production(body: dict = Body(...)):
        async def payload(raw):
            if not raw.get('preview_id') or not raw.get('run_id'):
                raise ValueError('请先预览生产同步')
            return raw
        try:
            return await send('sync_production', body, payload)
        except (ValueError, KeyError, TypeError) as exc:
            raise mapped_error(exc)

    @router.get('/plans/sources')
    async def sources():
        if production_collection is None:
            return {'plans': []}
        rows = await production_collection.find({}, {'plan_name': 1, 'jobs': 1, 'schedule_results': 1, 'schedule_result': 1, 'recommended_solver': 1}).sort('created_at', -1).limit(100).to_list(100)
        result = []
        for doc in rows:
            saved = doc.get('schedule_results') or {}
            single = doc.get('schedule_result') or {}
            solvers = [key for key, value in saved.items() if value.get('gantt_data')]
            if single.get('gantt_data') and single.get('solver_id') and single.get('solver_id') not in solvers:
                solvers.append(single.get('solver_id'))
            if not solvers:
                continue
            result.append({'id': str(doc['_id']), 'name': doc.get('plan_name', ''), 'job_count': len(doc.get('jobs') or []),
                           'solvers': solvers, 'recommended_solver': doc.get('recommended_solver') or single.get('solver_id'), 'can_preview': bool(solvers)})
        return {'plans': result}

    async def response(cid):
        doc = await service.await_command(cid)
        if not doc:
            raise HTTPException(404, "命令不存在")
        if doc["status"] == "failed":
            raise HTTPException(doc.get("code", 422), doc["error"])
        return JSONResponse({"command_id": cid, "status": doc["status"], "result": doc.get("result")}, status_code=202 if doc["status"] == "queued" else 200)

    async def send(kind, body, payload):
        body = dict(body)
        cid = body.pop("request_id", None) or uuid4().hex
        existing = await service.store.command(cid)
        if existing:
            if existing["kind"] != kind or existing["payload"].get("_request") != body:
                raise Conflict("幂等键已用于不同请求")
            return await response(cid)
        data = dict(await payload(body))
        data["_request"] = dict(body)
        await service.submit(kind, data, cid)
        if data.get("scheduled_at") and timestamp(data["scheduled_at"]) > service.clock():
            return JSONResponse({"command_id": cid, "status": "queued", "message": "预约已登记，到时由后台处理，主时钟继续"}, status_code=202)
        return await response(cid)

    def mapped_error(exc):
        return HTTPException(409 if isinstance(exc, Conflict) else 422, str(exc))

    @router.get("/current")
    async def current():
        return await service.current()

    @router.get("/stream")
    async def stream(request: Request):
        async def events():
            version = None
            while not await request.is_disconnected():
                value = await service.current()
                latest = (value.get("instance") or {}).get("version", 0)
                if version != latest:
                    version = latest
                    yield f"id: {latest}\nevent: snapshot\ndata: {json.dumps(value, ensure_ascii=False, allow_nan=False)}\n\n"
                else:
                    heartbeat = {"server_time": value["server_time"], "server_timestamp": value["server_timestamp"], "health": value["health"]}
                    yield f"event: heartbeat\ndata: {json.dumps(heartbeat, ensure_ascii=False)}\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.post("/plans/preview")
    async def preview(body: dict = Body(default={})):
        try:
            if body.get("source") == "production":
                plan = await native_plan(body, timestamp(body['start_at']) if body.get('start_at') else service.clock() + 30)
                result = await service.preview(plan)
                result.update(source_version=plan['source_manifest'][0]['sha256'], gaps=['已导入原生产计划；组装与配送尚未绑定，不虚构下游任务'], message='保留原甘特及设备配置，启用未开工仿真副本')
                return result
            raw_plan = body.get('plan')
            if raw_plan is None and not body.get('source') and not allow_implicit_standard:
                raise ValueError('请选择库内已排程计划；演示基线需明确选择，不自动绑定固定计划')
            if body.get('source') == 'custom' and raw_plan is None:
                raise ValueError('请提供完整计划JSON，不自动改用标准基线')
            return await service.preview(raw_plan if raw_plan is not None else standard_factory(timestamp(body['start_at']) if body.get('start_at') else service.clock() + 30))
        except (ValueError, KeyError, TypeError) as exc:
            raise mapped_error(exc)

    @router.post("/plans/activate")
    async def activate(body: dict = Body(default={})):
        async def payload(raw):
            plan = raw.get("plan")
            if raw.get('source') == 'chain':
                if not raw.get('preview_id'):
                    raise ValueError('请先预览校验计划衔接')
                return raw
            if plan is None and not raw.get('source') and not allow_implicit_standard:
                raise ValueError('请选择库内已排程计划，不自动启用固定基线')
            if raw.get('source') == 'custom' and plan is None:
                raise ValueError('请提供完整计划JSON，不自动改用标准基线')
            if raw.get('source') == 'production':
                plan = await native_plan(raw, timestamp(raw['start_at']) if raw.get('start_at') else service.clock() + 5)
            elif plan is None:
                plan = standard_factory(timestamp(raw["start_at"]) if raw.get("start_at") else service.clock() + 5)
            return {**raw, "plan": plan}
        try:
            return await send("activate", body, payload)
        except (ValueError, KeyError, TypeError) as exc:
            raise mapped_error(exc)

    @router.post("/events")
    async def register_event(body: dict = Body(...)):
        async def payload(raw):
            if raw.get("source", "manual_simulation") not in {"manual_simulation", "manual_feedback"}:
                raise ValueError("首版只接已声明的人工模拟/反馈，现场接口须独立适配")
            if not raw.get("run_id") or not raw.get("type"):
                raise ValueError("缺少运行实例或变化类型")
            if raw.get("scheduled_at"):
                raw = {**raw, "scheduled_at": timestamp(raw["scheduled_at"])}
                if raw["scheduled_at"] <= service.clock():
                    raise ValueError("预约发生时间必须晚于当前服务器时间")
                if raw.get("source", "manual_simulation") != "manual_simulation":
                    raise ValueError("人工确认反馈只能记录已发生事实，预约请使用人工模拟来源")
            return raw
        try:
            return await send("event", body, payload)
        except (ValueError, KeyError, TypeError) as exc:
            raise mapped_error(exc)

    @router.get("/commands/{cid}")
    async def command(cid: str):
        return await response(cid)

    @router.post("/adjustments")
    async def adjustment(body: dict = Body(...)):
        try:
            job = await service.request_adjustment(body["run_id"], body.get("request_id"))
            return {"id": job["_id"], "status": job["status"], "message": "后台计算，当前运行与时钟继续"}
        except (ValueError, KeyError, TypeError) as exc:
            raise mapped_error(exc)

    @router.get("/adjustments/{jid}")
    async def get_adjustment(jid: str):
        job = await service.store.job(jid)
        if not job:
            raise HTTPException(404, "调整任务不存在")
        result = {k: v for k, v in job.items() if k not in {"snapshot", "_id"}}
        result["id"] = jid
        current, _ = await service.store.read()
        result["stale"] = not current or current["run_id"] != job["run_id"] or current["constraint_version"] != job["snapshot"]["constraint_version"]
        return result

    @router.post("/adjustments/{jid}/apply")
    async def apply(jid: str, body: dict = Body(...)):
        async def payload(raw):
            return {**raw, "job_id": jid}
        try:
            return await send("apply", body, payload)
        except (ValueError, KeyError, TypeError) as exc:
            raise mapped_error(exc)

    @router.get("/history")
    async def history(limit: int = 100):
        state, _ = await service.store.read()
        if not state:
            return {"events": [], "adjustments": []}
        result = await service.store.history(state["run_id"], max(1, min(limit, 500)))
        for job in result["adjustments"]:
            job.pop("snapshot", None)
        return result

    @router.post("/assistant")
    async def assistant(body: dict = Body(...)):
        from .assistant import assist
        state, _ = await service.store.read()
        if not state:
            raise HTTPException(409, "请先启用运行计划")
        message = str(body.get("message", "")).strip()
        if not message or len(message) > 4000:
            raise HTTPException(422, "请输入1至4000字的描述")
        result = await asyncio.to_thread(assist, state, message, service.clock(), bool(body.get("use_llm", True)))
        if result.get("plan_request") and not result.get("prepared_event", {}).get("draft"):
            job = await service.request_adjustment(state["run_id"])
            result["adjustment_id"] = job["_id"]
        return result

    return router
