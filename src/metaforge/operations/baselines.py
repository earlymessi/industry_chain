"""Curated, editable case inputs. All execution still goes through normal chain validation."""
from __future__ import annotations
import copy
import json
from datetime import datetime, timedelta, timezone
from .sources import ROOT
from .models import timestamp
from .distributed import load_production_sources
from .chain_sources import supply_source, route_catalog, route_source, process_catalog
from .chain import build_chain

CASE_IDS = ('fridge-chain-v1', 'chain-demo-normal', 'chain-demo-supply', 'chain-demo-transport')
CASES = {key: ROOT / 'data/operations/baselines' / key for key in CASE_IDS}
ZONE = timezone(timedelta(hours=8))

def dataset_root(dataset, fallback=ROOT):
    if not dataset:
        return fallback
    if str(dataset).startswith('record:'):
        from .history import delivery_dataset
        return delivery_dataset(dataset.removeprefix('record:'))
    if dataset not in CASES:
        raise ValueError('未知案例数据集，不接受自定义文件路径')
    return CASES[dataset]

def list_baselines():
    from zhenjie.result_versions import status
    result = []
    for key, directory in CASES.items():
        if not (directory / 'definition.json').is_file(): continue
        definition = json.loads((directory / 'definition.json').read_text(encoding='utf-8'))
        publication = status(directory / 'zhenjie')
        result.append({'id': key, 'name': definition['name'], 'units': definition['units'], 'factory_count': len(definition['factories']),
                       'ready': publication['verified'] and (not key.startswith('chain-demo-') or (directory / 'assembly_result.json').is_file()), 'message': publication['message'], 'description': definition.get('description', ''),
                       'production_plan_id': definition['production_plan_id'], 'assembly_id': 'example:' + key if (directory / 'assembly_result.json').is_file() else '', 'example': key.startswith('chain-demo-')})
    return result

async def make_config(case_id, loader, start):
    if case_id not in CASES: raise ValueError('未知完整案例')
    directory = dataset_root(case_id)
    definition = json.loads((directory / 'definition.json').read_text(encoding='utf-8'))
    supply = supply_source(directory)
    selections = [{**{k: copy.deepcopy(factory[k]) for k in ('factory_id', 'job_indices', 'source_zero_offset_hours', 'job_names')},
                   'plan_id': definition['production_plan_id'], 'solver_id': definition['solver_id'], 'time_unit': definition['time_unit'], 'origin_offset_hours': factory.get('origin_offset_hours', 0)}
                  for factory in definition['factories']]
    c = {'coherence_version': 1, 'source_dataset': case_id, 'baseline_case': case_id, 'name': definition['name'], 'units': definition['units'],
         'start_at': start, 'production': copy.deepcopy(selections[0]), 'production_sources': selections,
         'assembly_mode': 'supplement', 'assembly_id': '', 'assembly_origin_at': '', 'assembly_time_unit': 'minutes',
         'delivery_mode': 'unbound', 'route_id': '', 'calendar': {'mode': 'continuous', 'days': definition.get('calendar_days', 7), 'begin_hour': 8, 'end_hour': 20},
         'transfer_minutes': 5, 'post_minutes': 5, 'loading_minutes': 15, 'confirmed': True,
         'parts': [], 'purchased': [], 'stock_overrides': {}, 'arrival_overrides': {}, 'additional_supplies': [],
         'procurement_orders': [], 'procurement_links': {}, 'inbound_shipments': [], 'customer_commitments': {}, 'customer_windows_hard': True,
         'assembly_bom': {'product_id': definition['product_id'], 'spec': definition['spec'], 'uom': '台', 'revision': 'CASE-BOM-1', 'assembly_site': 'CASE-ASSEMBLY', 'lines': []},
         'dispatch_product_id': definition['product_id'], 'dispatch_spec': definition['spec'], 'dispatch_uom': '台', 'dispatch_depot_id': '',
         'case_assumptions': definition['assumptions']}
    native = await load_production_sources(c, loader, start)
    order_rows = {o['id']: o for o in native['orders']}
    slots = {s['task_id']: s for s in native['schedule']}
    routes = route_catalog(directory)
    chosen = None
    for r in routes:
        candidate = route_source(r['id'], directory)
        ids = {str(int(float(s['cust_id']))) for s in candidate['stops'] if s['node_type'] == 'customer'}
        if sum(float(customer['demand']) for customer in candidate['customers'] if str(int(float(customer['cust_id']))) in ids) == c['units']:
            chosen = candidate; break
    if not chosen or not chosen['publication']['verified']:
        raise ValueError('完整案例缺少同次求解的5台配送结果，请运行基线物流生成脚本')
    c.update(route_id=chosen['route']['id'], vehicle_capacity=float(chosen['publication']['effective_config']['VEHICLE_CAP']), dispatch_depot_id=chosen['route']['start_depot'])
    for factory in definition['factories']:
        factory_orders = [o for o in native['orders'] if o.get('business_source', {}).get('factory_id') == factory['factory_id']]
        if len(factory_orders) != 1 or factory_orders[0]['name'] not in factory['job_names']:
            raise ValueError('库内工单范围或名称已变化，请重新确认案例定义')
        order = factory_orders[0]; lid = 'SELF-' + factory['factory_id']
        line = {'id': lid, 'material_id': factory['material_id'], 'spec': factory['spec'], 'uom': factory['uom'], 'per_unit': 1, 'process_id': factory['process_id']}
        c['assembly_bom']['lines'].append(line)
        c['parts'].append({'order_id': order['id'], 'name': order['name'], 'enabled': True, 'material_id': 'self:' + order['id'],
                           'produced_quantity': c['units'], 'per_unit': 1, 'process_id': factory['process_id'], 'factory_id': factory['factory_id'],
                           'business_source': order.get('business_source', {}), 'bom_line_id': lid, 'business_material_id': factory['material_id'],
                           'spec': factory['spec'], 'uom': factory['uom'], 'mapping_confirmed': True, 'quantity_source': 'confirmed_case_batch'})
        finish = max(slots[tid]['end_at'] for tid in order['completion_task_ids'])
        depart = finish + 15 * 60
        c['inbound_shipments'].append({'id': factory['factory_id'], 'trip_group': factory['factory_id'], 'source_id': order['id'],
            'vehicle_id': 'CASE-TRUCK-' + factory['factory_id'], 'from_site': factory['factory_id'], 'to_site': 'CASE-ASSEMBLY',
            'material_id': factory['material_id'], 'spec': factory['spec'], 'uom': factory['uom'], 'quantity': c['units'],
            'load_units': c['units'], 'capacity': 10, 'capacity_uom': '标准箱', 'ship_at': depart,
            'loading_minutes': 10, 'travel_minutes': definition.get('factory_travel_minutes', 45), 'unloading_minutes': 10, 'arrival_at': depart + (20 + definition.get('factory_travel_minutes', 45)) * 60})
    suppliers = {}
    processes = {p['name']: p['id'] for p in process_catalog()}
    weights = {'compressor': 1, 'circuit_board': .1, 'sensor': .05, 'wire_harness': .1, 'foam_material': .2,
               'door_gasket': .1, 'hinge_kit': .1, 'metal_panel': 1, 'copper_tube': .25, 'packing_box': .25}
    for item in supply['catalog']:
        mid = item['id']; supplier = item['supplier']; group = suppliers.setdefault(supplier, len(suppliers))
        pid = processes.get(item['workstation'], 8 if item['workstation'] == '检测打包' else None)
        if pid is None: raise ValueError('外购件无法对应当前组装工序')
        per_unit = .8 if mid == 'foam_material' else 1
        lid = 'BUY-' + mid; quantity = c['units'] * per_unit
        stock = float(supply['state']['materials'][mid]['on_hand']); future = quantity - stock
        c['assembly_bom']['lines'].append({'id': lid, 'material_id': mid, 'spec': item['spec'], 'uom': item['unit'], 'per_unit': per_unit, 'process_id': pid})
        c['purchased'].append({'material_id': mid, 'name': item['name'], 'enabled': True, 'per_unit': per_unit, 'process_id': pid,
                               'bom_line_id': lid, 'business_material_id': mid, 'spec': item['spec'], 'uom': item['unit'],
                               'supplier_id': supplier, 'mapping_confirmed': True})
        c['stock_overrides'][mid] = stock
        if future <= 0: continue
        depart = start + (30 + group * 5 + definition.get('supplier_delay_minutes', 0)) * 60; arrival = depart + 55 * 60
        supply_id = 'CASE-SUPPLY-' + mid; po_id = 'CASE-PO-' + mid
        c['additional_supplies'].append({'id': supply_id, 'name': item['name'] + '采购到货', 'material_id': mid, 'quantity': future, 'available_at': arrival})
        c['procurement_orders'].append({'id': po_id, 'material_id': mid, 'supplier_id': supplier, 'quantity': future,
            'spec': item['spec'], 'uom': item['unit'], 'origin_site': supplier, 'delivery_site': 'CASE-ASSEMBLY', 'ready_at': start + 20 * 60})
        c['procurement_links']['chain:manual-supply:' + supply_id] = po_id
        c['inbound_shipments'].append({'id': 'CASE-IN-' + mid, 'trip_group': 'CASE-SUPPLIER-' + str(group),
            'source_id': 'chain:manual-supply:' + supply_id, 'vehicle_id': 'CASE-SUPPLIER-' + str(group),
            'from_site': supplier, 'to_site': 'CASE-ASSEMBLY', 'material_id': mid, 'spec': item['spec'], 'uom': item['unit'],
            'quantity': future, 'load_units': future * weights[mid], 'capacity': 12, 'capacity_uom': '标准箱',
            'ship_at': depart, 'loading_minutes': 10, 'travel_minutes': 35, 'unloading_minutes': 10, 'arrival_at': arrival})
    # Compute upstream readiness before recommending a delivery day; never move it silently after confirmation.
    upstream = build_chain(native, c, supply)
    batch = next(o for o in upstream['orders'] if o['id'] == 'chain:assembly:batch')
    ready = max(r['end_at'] for r in upstream['schedule'] if r['task_id'] in batch['completion_task_ids']) + (c['loading_minutes'] + 30) * 60
    dispatch_day = datetime.fromtimestamp(ready, ZONE).replace(hour=8, minute=0, second=0, microsecond=0)
    if dispatch_day.timestamp() < ready: dispatch_day += timedelta(days=1)
    c.update(delivery_mode='saved', delivery_date=dispatch_day.date().isoformat(), delivery_origin_at=dispatch_day.timestamp())
    c['customer_commitments'] = {'38': dispatch_day.replace(hour=12).timestamp(), '36': dispatch_day.replace(hour=13).timestamp()}
    # The final full build must pass all ordinary business/time/solver checks as well.
    assembly = None
    if (directory / 'assembly_result.json').is_file():
        from .chain_sources import assembly_source
        assembly = assembly_source('example:' + case_id, None)
        c.update(assembly_mode='saved', assembly_id=assembly['id'], assembly_origin_at=start)
    plan = build_chain(native, c, supply, assembly=assembly, logistics=chosen)
    c['confirmed'] = False
    return {'config': c, 'summary': plan['chain_summary'], 'time_mapping': plan['time_mapping'], 'task_count': len(plan['tasks']),
            'message': '案例参数已载入；工厂/BOM/采购/运输为显式案例配置，核对后预览并启用'}
