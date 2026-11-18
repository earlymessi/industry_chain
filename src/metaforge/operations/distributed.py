"""Combine selected native factory plans, retaining physical device identity."""
import copy
from .sources import fingerprint

async def load_production_sources(config, loader, start):
    selections = config.get('production_sources') or []
    if not selections:
        return await loader(config['production'], start)
    result = None
    resource_sites, orders, stocks, manifests = {}, set(), {}, []
    seen_sources = set()
    source_versions = {}
    for selection in selections:
        factory = str(selection.get('factory_id') or '').strip()
        if not factory:
            raise ValueError('每份自有工厂计划必须明确工厂标识')
        source_key = (str(selection.get('plan_id')), tuple(sorted(selection.get('job_indices') or [])))
        if source_key in seen_sources:
            raise ValueError('同一生产计划不能复制到多个工厂重复产生部件')
        seen_sources.add(source_key)
        offset = float(selection.get('origin_offset_hours') or 0)
        if not 0 <= offset <= 672:
            raise ValueError('工厂计划起点偏移须为0至672小时')
        native = await loader(selection, start + offset * 3600)
        manifest = native['source_manifest'][0]
        version_key = (str(selection.get('plan_id')), manifest.get('solver', native.get('source_solver')))
        raw_version = manifest.get('source_sha256', manifest['sha256'])
        if version_key in source_versions and source_versions[version_key] != raw_version:
            raise ValueError('同一生产计划在读取期间已变化，请重新预览，不能拼接不同版本的工厂工单')
        source_versions[version_key] = raw_version
        if result is None:
            result = copy.deepcopy(native)
            for key in ('orders', 'tasks', 'resources', 'stock', 'schedule', 'source_manifest'):
                result[key] = []
        for order in native['orders']:
            if order['id'] in orders:
                raise ValueError('生产工单被不同来源重复引用')
            orders.add(order['id'])
            known = order.setdefault('business_source', {}).get('factory_id')
            if known is not None and str(known) != factory:
                raise ValueError('所选工厂与原工单归属不一致')
            order['business_source']['factory_id'] = factory
        for resource in native['resources']:
            rid = resource['id']
            if rid in resource_sites and resource_sites[rid] != factory:
                raise ValueError(f'设备{rid}不能同时属于{resource_sites[rid]}和{factory}，不复制物理设备')
            if rid not in resource_sites:
                resource_sites[rid] = factory
                resource['factory_id'] = factory
                result['resources'].append(resource)
        for stock in native['stock']:
            key = (stock['location'], stock['material_id'])
            if key in stocks and stock['quantity'] != stocks[key]['quantity']:
                raise ValueError('不同来源对同一原料库存截面不一致')
            stocks[key] = stock
        result['orders'] += native['orders']; result['tasks'] += native['tasks']; result['schedule'] += native['schedule']
        manifests.append({**native['source_manifest'][0], 'factory_id': factory, 'origin_at': native['source_manifest'][0].get('origin_at', native['start_at'])})
    result['stock'] = list(stocks.values())
    result['start_at'] = start
    result['production_sources'] = manifests
    versions = [{k: v for k, v in manifest.items() if k != 'origin_at'} for manifest in manifests]
    result['source_plan_id'] = 'multi:' + fingerprint(versions)[:16]
    result['source_solver'] = 'mixed'
    result['source_manifest'] = [{'module': 'production', 'id': result['source_plan_id'], 'time_unit': 'mixed', 'sha256': fingerprint(versions)}]
    result['name'] = '自有分布式工厂联合生产来源'
    return result
