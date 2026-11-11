from __future__ import annotations

import asyncio
import copy
from uuid import uuid4

from fastapi import Body, HTTPException

from .chain import build_chain
from .chain_sources import assembly_catalog, assembly_source, process_catalog, route_catalog, route_source, supply_source
from .models import timestamp
from .sources import ROOT
from .store import Conflict


def attach(router, service, native_loader, assembly_reader=None, source_root=ROOT):
    async def build(config):
        config = copy.deepcopy(config)
        config['start_at'] = timestamp(config['start_at']) if config.get('start_at') else service.clock() + 120
        native = await native_loader(config['production'], config['start_at'])
        assembly = await asyncio.to_thread(assembly_source, config.get('assembly_id'), assembly_reader) if config.get('assembly_mode') == 'saved' else None
        logistics = route_source(config.get('route_id'), source_root) if config.get('delivery_mode') == 'saved' else None
        return await asyncio.to_thread(build_chain, native, config, supply_source(source_root), assembly, logistics), config

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
    async def sources():
        assembly = await asyncio.to_thread(assembly_catalog, assembly_reader)
        supply = supply_source(source_root)
        return {'assembly': assembly, 'processes': process_catalog(), 'routes': route_catalog(source_root),
                'supply': supply, 'note': '评估与路线需绑定本批数量；来源缺失不自动采用演示快照'}

    @router.get('/plans/chain/route')
    async def route(route_id: str):
        try:
            data = route_source(route_id, source_root)
            ids = {str(int(float(s['cust_id']))) for s in data['stops'] if s['node_type'] == 'customer'}
            return {**data, 'customers': [c for c in data['customers'] if str(int(float(c['cust_id']))) in ids]}
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc))

    @router.post('/plans/chain/production')
    async def production(body: dict = Body(...)):
        try:
            native = await native_loader(body, timestamp(body['start_at']) if body.get('start_at') else service.clock() + 120)
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
            raise HTTPException(409 if isinstance(exc, Conflict) else 422, str(exc))
