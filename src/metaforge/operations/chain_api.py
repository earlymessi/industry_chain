from __future__ import annotations

import asyncio
import copy
from uuid import uuid4

from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse

from .chain import build_chain
from .chain_sources import assembly_catalog, assembly_source, process_catalog, route_catalog, route_source, supply_source
from .models import timestamp
from .sources import ROOT
from .store import Conflict
from .baselines import dataset_root, list_baselines, make_config


def attach(router, service, native_loader, assembly_reader=None, source_root=ROOT):
    async def build(config):
        config = copy.deepcopy(config)
        if config.get('coherence_version') != 1:
            raise ValueError('请补齐独立组装BOM、自有工厂/供应商和采购运输对应关系，旧配置不能仅按数量启用')
        config['start_at'] = timestamp(config['start_at']) if config.get('start_at') else service.clock() + 120
        from .distributed import load_production_sources
        native = await load_production_sources(config, native_loader, config['start_at'])
        assembly = await asyncio.to_thread(assembly_source, config.get('assembly_id'), assembly_reader) if config.get('assembly_mode') == 'saved' else None
        root = dataset_root(config.get('source_dataset'), source_root)
        logistics = route_source(config.get('route_id'), root) if config.get('delivery_mode') == 'saved' else None
        return await asyncio.to_thread(build_chain, native, config, supply_source(root), assembly, logistics), config

    from .history_api import attach as attach_history
    attach_history(router, service, build)

    async def load_preview(key, state):
        preview = await service.store.get_preview(key)
        if not preview or preview.get('kind') != 'chain' or preview['expires_at'] < service.clock():
            raise Conflict('衔接预览不存在或已过期，请重新预览')
        if preview.get('run_id') != (state or {}).get('run_id'):
            raise Conflict('预览后活动运行实例已变化，请重新预览')
        plan, _ = await build(preview['config'])
        if plan['chain_source_versions'] != preview['source_versions']:
            raise Conflict('预览后生产/组装/供给/路线来源已变化，请重新预览衔接')
        return plan
    service.chain_loader = load_preview

    @router.get('/plans/chain/sources')
    async def sources(dataset: str = ''):
        try: root = dataset_root(dataset, source_root)
        except ValueError as exc: raise HTTPException(422, str(exc))
        assembly = await asyncio.to_thread(assembly_catalog, assembly_reader)
        supply = supply_source(root)
        return {'assembly': assembly, 'processes': process_catalog(), 'routes': route_catalog(root),
                'supply': supply, 'note': '评估与路线需绑定本批数量；来源缺失不自动采用演示快照'}

    @router.get('/plans/chain/route')
    async def route(route_id: str, dataset: str = ""):
        try:
            data = route_source(route_id, dataset_root(dataset, source_root))
            ids = {str(int(float(s['cust_id']))) for s in data['stops'] if s['node_type'] == 'customer'}
            return {**data, 'customers': [c for c in data['customers'] if str(int(float(c['cust_id']))) in ids]}
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc))

    @router.get('/plans/chain/baselines')
    async def baselines():
        return {'cases': list_baselines()}

    @router.get('/plans/chain/examples/{case_id}')
    async def example(case_id: str):
        try:
            item = next((c for c in list_baselines() if c['id'] == case_id and c.get('example')), None)
            if not item: raise ValueError('未知示范案例')
            import json
            directory = dataset_root(case_id)
            definition = json.loads((directory / 'definition.json').read_text(encoding='utf-8'))
            return {**item, 'assembly': assembly_source(item['assembly_id'], None), 'definition':definition, 'supply':supply_source(directory), 'processes':process_catalog()}
        except (ValueError, KeyError, OSError) as exc: raise HTTPException(422, str(exc))

    @router.post('/plans/chain/baseline')
    async def baseline(body: dict = Body(...)):
        try:
            start = timestamp(body['start_at']) if body.get('start_at') else service.clock() + 15 * 60
            if start < service.clock() + 5:
                raise ValueError('案例起点应晚于当前时刻，请重新载入')
            return await make_config(body.get('case_id', 'fridge-chain-v1'), native_loader, start)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc))

    @router.post('/plans/chain/rebase')
    async def rebase(body: dict = Body(...)):
        try:
            from datetime import datetime, timezone, timedelta
            from .cases import rebase_case
            config = copy.deepcopy(body['config'])
            if len(str(config)) > 500_000: raise ValueError('衔接配置过大')
            start = timestamp(body['start_at']) if body.get('start_at') else service.clock() + 15 * 60
            if start < service.clock() + 5: raise ValueError('请使用晚于当前时刻的新起点')
            origin = config.get('delivery_origin_at')
            if config.get('delivery_mode') == 'saved' and origin is None and config.get('delivery_date'):
                origin = datetime.fromisoformat(config['delivery_date'] + 'T08:00:00+08:00').timestamp()
                config['delivery_origin_at'] = origin
            config = rebase_case({'mode': 'simulation', 'start_at': config['start_at'], 'chain_config': config}, start)['chain_config']
            config['confirmed'] = False
            return {'config': config, 'message': '草稿所有绝对时刻已整体平移；当前运行保持原状，请重新预览'}
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc))

    @router.post('/plans/chain/production')
    async def production(body: dict = Body(...)):
        try:
            from .distributed import load_production_sources
            native = await load_production_sources({**body, 'production': body}, native_loader, timestamp(body['start_at']) if body.get('start_at') else service.clock() + 120)
            return {'orders': native['orders'], 'source_version': native['source_manifest'][0]['sha256'],
                    'time_origin_at': native['start_at'], 'name': native['name'], 'task_count': len(native['tasks'])}
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(409 if isinstance(exc, Conflict) else 422, str(exc))

    @router.get('/plans/chain/draft')
    async def draft():
        return {'config': await service.store.get_chain_draft()}

    @router.put('/plans/chain/draft')
    async def save(body: dict = Body(...)):
        if len(str(body)) > 500_000:
            raise HTTPException(422, '衔接配置过大')
        await service.store.save_chain_draft(body)
        return {'saved': True}

    @router.post('/plans/chain/preview')
    async def preview(body: dict = Body(...)):
        try:
            if body.get('start_at') and timestamp(body['start_at']) < service.clock() + 5:
                raise ValueError('计划起点已过或即将过去，请明确选择新的生效日期；不会自动平移已保存配置')
            plan, config = await build(body)
            state, _ = await service.store.read()
            key = uuid4().hex
            await service.store.put_preview({'_id': key, 'kind': 'chain', 'config': config, 'run_id': (state or {}).get('run_id'),
                                             'source_versions': plan['chain_source_versions'], 'expires_at': service.clock() + 300})
            result = await service.preview(plan)
            return {**result, 'preview_id': key, 'summary': plan['chain_summary'], 'time_mapping': plan['time_mapping'],
                    'requires_new_run': bool(state), 'previous_run_id': (state or {}).get('run_id')}
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            from .coherence import CoherenceError
            if isinstance(exc, CoherenceError):
                return JSONResponse({'detail': str(exc), 'coherence': exc.report}, status_code=422)
            raise HTTPException(409 if isinstance(exc, Conflict) else 422, str(exc))
