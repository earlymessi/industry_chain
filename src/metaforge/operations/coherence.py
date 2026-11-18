"""Business contracts independent of the schedules: BOM -> sources -> inbound trips -> assembly."""
from __future__ import annotations

import copy
from collections import defaultdict

from .models import number, timestamp


class CoherenceError(ValueError):
    def __init__(self, conflicts):
        self.report = {'passed': False, 'conflicts': conflicts}
        super().__init__('；'.join(f'{c["target"]}：{c["message"]}' for c in conflicts[:5]))


def apply_coherence(plan, config, supply, logistics=None):
    errors, checks, manual = [], [], []
    def check(ok, target, message):
        (checks if ok else errors).append({'target': str(target), 'message': message})
    def text(row, field):
        return str(row.get(field) or '').strip()
    def qty(value, label):
        try:
            return number(value, label, .000001)
        except (ValueError, TypeError, OverflowError):
            check(False, label, '需要明确的正数量'); return 0
    def at(value, label):
        try:
            return timestamp(value)
        except (ValueError, TypeError, OverflowError):
            check(False, label, '需要包含时区的明确日期'); return plan['start_at']
    bom = config.get('assembly_bom') or {}
    for field, label in [('product_id', '成品编码'), ('spec', '成品规格'), ('revision', 'BOM版本'), ('assembly_site', '组装地点'), ('uom', '成品计量单位')]:
        check(bool(text(bom, field)), label, '必须明确填写，不能只按数量拼接')
    site = text(bom, 'assembly_site')
    lines = bom.get('lines') or []
    check(bool(lines), '组装BOM', '需要独立于供给来源的完整需求清单')
    line_map = {}
    for line in lines:
        lid = text(line, 'id')
        check(bool(lid) and lid not in line_map, 'BOM行', '需求行标识必须非空且唯一')
        line_map[lid] = line
        for field in ('material_id', 'spec', 'uom'):
            check(bool(text(line, field)), lid, f'必须确认物料编码、规格和单位，缺少{field}')
        qty(line.get('per_unit'), f'{lid}每台需求')
    allocated = defaultdict(float)
    selected_parts = [r for r in config.get('parts', []) if r.get('enabled', True)]
    purchased = [r for r in config.get('purchased', []) if r.get('enabled', True)]
    check(len({r.get('material_id') for r in purchased}) == len(purchased), '外购关联', '同一外购物料不能重复登记用量')
    orders = {o['id']: o for o in plan['orders']}
    catalog = {p['id']: p for p in supply['catalog']}
    source_meta = {}
    device_sites = {}
    def binding(row, label, native=None):
        lid = text(row, 'bom_line_id'); line = line_map.get(lid)
        check(line is not None, label, '必须关联一条独立BOM需求，不能根据所选来源反推需求')
        if line:
            for field, source_field in [('material_id', 'business_material_id'), ('spec', 'spec'), ('uom', 'uom')]:
                check(text(row, source_field) == text(line, field), label, f'{field}与BOM不一致，不允许自动替料或换单位')
            check(int(row.get('process_id', -1)) == int(line.get('process_id', -2)), label, '消耗工序与BOM不一致')
            used = qty(row.get('per_unit'), label + '每台分配')
            if text(line, 'uom') in {'件', '个', '台', '套'}:
                check(abs(used - round(used)) < 1e-7, label, '离散部件不能按半件拆分给每台整机')
            allocated[lid] += used
        check(row.get('mapping_confirmed') is True, label, '来源与物料的对应关系需明确确认')
        native = native or {}
        for key, dest in [('output_material_id', 'business_material_id'), ('spec', 'spec'), ('uom', 'uom')]:
            if native.get(key):
                check(str(native[key]) == text(row, dest), label, f'原来源的{key}与声明不一致')
        if not native.get('output_material_id'):
            manual.append({'target': label, 'note': '原来源缺少完整物料身份，采用用户确认的映射，不宣称来源已自动证明'})
        return lid
    for row in selected_parts:
        order = orders.get(row['order_id'], {})
        native = order.get('business_source') or {}
        label = row.get('name') or order.get('name') or row['order_id']
        lid = binding(row, label, native)
        factory = text(row, 'factory_id')
        check(bool(factory), label, '必须明确自有工厂及发货地点')
        if native.get('factory_id'):
            check(factory == str(native['factory_id']), label, '声明工厂与原生产工单归属不一致')
        for task in plan['tasks']:
            if task.get('order_id') == row['order_id']:
                for alternative in task['alternatives']:
                    rid = alternative['resource_id']
                    check(rid not in device_sites or device_sites[rid] == factory, label, '同一生产设备不能被声明为两个不同工厂的资源')
                    device_sites[rid] = factory
        terminal = order.get('completion_task_ids', [None])[0]
        mid = row.get('material_id') or f'self:{row["order_id"]}'
        source_meta[row['order_id']] = {'type': 'factory', 'material_id': mid, 'business_material_id': text(row, 'business_material_id'),
            'spec': text(row, 'spec'), 'uom': text(row, 'uom'), 'bom_line_id': lid, 'from_site': factory,
            'quantity': float(row['per_unit']) * config['units'], 'terminal': terminal, 'row': row}
    purchased_map = {}
    for row in purchased:
        label = row.get('name') or row['material_id']; item = catalog.get(row['material_id'], {})
        binding(row, label, {'output_material_id': item.get('id'), 'spec': item.get('spec'), 'uom': item.get('unit')})
        check(bool(text(row, 'supplier_id')), label, '必须明确外部供应商')
        known_supplier = item.get('supplier_id') or item.get('supplier')
        if known_supplier:
            check(str(known_supplier) == text(row, 'supplier_id'), label, '所选供应商与原采购目录不一致')
        purchased_map[row['material_id']] = row
    for lid, line in line_map.items():
        check(abs(allocated[lid] - float(line.get('per_unit') or 0)) < 1e-6, lid,
              f'需求每台{line.get("per_unit")}，自有工厂与采购合计分配{allocated[lid]:g}，存在缺项/多配')
    po_map = {}
    for po in config.get('procurement_orders', []):
        pid = text(po, 'id'); check(bool(pid) and pid not in po_map, '采购单', '采购单标识必须唯一'); po_map[pid] = po
        qty(po.get('quantity'), pid + '采购数量')
        for field in ('supplier_id', 'material_id', 'spec', 'uom', 'origin_site', 'delivery_site'):
            check(bool(text(po, field)), pid, f'采购单缺少{field}')
        check(text(po, 'delivery_site') == site, pid, '采购收货地点与本批组装地点不一致')
    purchase_usage = defaultdict(float)
    additional = {'chain:manual-supply:' + str(r.get('id')): r for r in config.get('additional_supplies', [])}
    raw_deliveries = {'chain:supply:' + str(r.get('id')): r for r in supply['state'].get('deliveries', [])}
    links = config.get('procurement_links') or {}
    for shipment in plan['supplies']:
        row = purchased_map.get(shipment['material_id'])
        if row is None:
            continue
        raw = additional.get(shipment['id']) or raw_deliveries.get(shipment['id']) or {}
        po_id = links.get(shipment['id']) or raw.get('purchase_order_id')
        po = po_map.get(po_id)
        check(po is not None, shipment['id'], '未来到货必须关联采购单，不能凭数量和ETA虚构采购供给')
        if not po:
            continue
        for key, expected in [('supplier_id', text(row, 'supplier_id')), ('material_id', shipment['material_id']), ('spec', text(row, 'spec')), ('uom', text(row, 'uom'))]:
            check(text(po, key) == expected, shipment['id'], f'采购单{key}与需求/供应商不一致')
        if raw.get('supplier_id'):
            check(str(raw['supplier_id']) == text(po, 'supplier_id'), shipment['id'], '来源发运记录与采购单供应商不一致')
        purchase_usage[po_id] += shipment['quantity']
        source_meta[shipment['id']] = {'type': 'purchase', 'material_id': shipment['material_id'], 'business_material_id': shipment['material_id'],
            'spec': text(row, 'spec'), 'uom': text(row, 'uom'), 'bom_line_id': row.get('bom_line_id'),
            'from_site': text(po, 'origin_site'), 'quantity': shipment['quantity'], 'supply': shipment,
            'ready_at': at(po.get('ready_at'), str(po_id) + '备货时间'), 'expected_arrival_at': shipment['available_at'], 'purchase_order_id': po_id}
    for pid, used in purchase_usage.items():
        check(used <= float(po_map[pid].get('quantity') or 0) + 1e-7, pid, '同一采购数量被重复计入或分配超额')
    if config.get('delivery_mode') == 'saved':
        check(text(config, 'dispatch_product_id') == text(bom, 'product_id'), '成品配送', '配送产品必须与本批组装成品一致')
        check(text(config, 'dispatch_spec') == text(bom, 'spec') and text(config, 'dispatch_uom') == text(bom, 'uom'), '成品配送', '配送规格及单位必须与本批成品一致')
        if logistics:
            check(str(config.get('dispatch_depot_id', '')) == str(logistics['route']['start_depot']), '出库地点', '成品仓与所选路线起点仓不对应，不能跨仓瞬移')
            customer_ids = {str(int(float(r['cust_id']))) for r in logistics['stops'] if r['node_type'] == 'customer'}
            for customer in logistics['customers']:
                cid = str(int(float(customer['cust_id'])))
                if cid not in customer_ids:
                    continue
                for source_field, expected in [('product_id', text(bom, 'product_id')), ('spec', text(bom, 'spec')), ('uom', text(bom, 'uom'))]:
                    if customer.get(source_field):
                        check(str(customer[source_field]) == expected, f'客户{cid}', f'原订单{source_field}与本批成品不一致')
                if not customer.get('product_id'):
                    manual.append({'target': f'客户{cid}', 'note': '原物流订单未记录产品身份，采用用户明确绑定，不宣称自动核实原订单产品'})
            native_cap = logistics.get('publication', {}).get('effective_config', {}).get('VEHICLE_CAP')
            if native_cap is not None:
                check(abs(float(config.get('vehicle_capacity') or 0) - float(native_cap)) < 1e-6, '车辆容量', '与所选物流求解配置不一致，不能任意改变')
            check(logistics.get('publication', {}).get('verified') is True, '配送来源', '订单/参数与路线没有同次求解版本证明，请在物流资源管控重新计算并保存')
    shipment_rows = config.get('inbound_shipments') or []
    by_source = defaultdict(list)
    for trip in shipment_rows:
        source_id = text(trip, 'source_id'); meta = source_meta.get(source_id)
        check(meta is not None, trip.get('id', '运输'), '运输必须关联本批工厂产出或采购到货批次')
        if meta:
            by_source[source_id].append(trip)
    for key, meta in source_meta.items():
        trips = by_source[key]
        remote = meta['from_site'] != site
        check(len(trips) == (1 if remote or meta['type'] == 'purchase' else 0) or (not remote and len(trips) == 1), key,
              '跨工厂/供应商到货必须有且仅有一条明确运输；本版不猜测拆批及中转')
        for trip in trips:
            target = trip.get('id') or key
            check(text(trip, 'from_site') == meta['from_site'] and text(trip, 'to_site') == site, target, '运输起讫地点与供给、组装地点不一致')
            check(text(trip, 'material_id') == meta['business_material_id'], target, '运输物料与来源/BOM不一致')
            check(text(trip, 'spec') == meta['spec'] and text(trip, 'uom') == meta['uom'], target, '运输规格/单位不一致')
            quantity = qty(trip.get('quantity'), target + '运输数量')
            check(abs(quantity - meta['quantity']) < 1e-6, target, '运输数量与所关联供给/本批分配不守恒')
            capacity = qty(trip.get('capacity'), target + '车辆容量')
            check(capacity >= qty(trip.get('load_units'), target + '折算载荷'), target, '运输批次超过车辆容量')
            check(bool(text(trip, 'vehicle_id')), target, '运输必须使用明确车辆，不能以一个到货时间代替运力')
            depart = at(trip.get('ship_at'), target + '发运时间')
            travel = qty(trip.get('travel_minutes'), target + '行驶分钟数')
            load = max(0, float(trip.get('loading_minutes') or 0)); unload = max(0, float(trip.get('unloading_minutes') or 0))
            arrival = depart + (load + travel + unload) * 60
            if trip.get('arrival_at'):
                check(abs(at(trip['arrival_at'], target + '到货时间') - arrival) < 1, target, '到货时间早于或不符合装载、行驶和卸货过程')
            if meta.get('expected_arrival_at') is not None:
                check(abs(meta['expected_arrival_at'] - arrival) < 1, target, '采购到货ETA与实际装卸/运输时间不对应，请明确修正')
            if meta.get('terminal'):
                terminal = next((s for s in plan.get('schedule', []) if s['task_id'] == meta['terminal']), None)
                check(terminal is not None and depart + 1e-6 >= terminal['end_at'], target,
                      '无可行安排：工厂发运不能早于所关联部件的生产完成')
            if meta.get('ready_at'):
                check(depart >= meta['ready_at'], target, '采购尚未备好货，车辆不能提前发运')
    groups = defaultdict(list)
    for trip in shipment_rows:
        groups[str(trip.get('trip_group') or trip.get('id'))].append(trip)
    for gid, group in groups.items():
        first = group[0]
        check(bool(first.get('capacity_uom')), gid, '需明确运力计量单位及物料载荷折算')
        for other in group[1:]:
            for field in ('vehicle_id', 'capacity', 'capacity_uom', 'ship_at', 'loading_minutes', 'travel_minutes', 'unloading_minutes', 'from_site', 'to_site'):
                check(other.get(field) == first.get(field), gid, '同一车次的车辆、容量、时刻、起讫及耗时必须一致')
        load = sum(qty(row.get('load_units'), gid + '折算载荷') for row in group)
        check(load <= float(first.get('capacity') or 0) + 1e-7, gid, '合车后的折算载荷超过车辆容量')
    if errors:
        raise CoherenceError(errors)
    tasks = {t['id']: t for t in plan['tasks']}
    resources = {r['id']: r for r in plan['resources']}
    depot = str(config.get('dispatch_depot_id') or '')
    def node(value):
        return 'logistics:depot:' + depot if value == site and depot else 'site:' + value
    transport_ids = []
    group_tasks = {}
    purchase_dependencies = defaultdict(set)
    for source_id, meta in source_meta.items():
        origin_buffer = 'source:' + source_id
        incoming = by_source[source_id]
        if meta['type'] == 'factory':
            for output in tasks[meta['terminal']]['outputs']:
                if output['material_id'] == meta['material_id']:
                    output['location'] = origin_buffer
                    output['business_identity'] = {k: meta[k] for k in ('business_material_id', 'spec', 'uom', 'bom_line_id', 'from_site')}
        else:
            meta['supply']['location'], meta['supply']['available_at'] = origin_buffer, meta['ready_at']
            meta['supply']['purchase_order_id'] = meta['purchase_order_id']
            meta['supply']['role'] = 'supplier_ready'
            meta['supply']['name'] = '供方备货 · ' + str(meta['purchase_order_id'])
            meta['supply']['expected_arrival_at'] = meta['expected_arrival_at']
        destination_buffer = 'receiving:' + source_id if incoming else origin_buffer
        new_predecessors = []
        for trip in incoming:
            tid = 'inbound:' + str(trip.get('trip_group') or trip['id']); rid = 'logistics:vehicle:' + str(trip['vehicle_id'])
            depart = timestamp(trip['ship_at'])
            duration = sum(float(trip.get(k) or 0) for k in ('loading_minutes', 'travel_minutes', 'unloading_minutes')) * 60
            if rid not in resources:
                r = {'id': rid, 'name': '入厂车辆 ' + str(trip['vehicle_id']), 'kind': 'vehicle', 'capacity': float(trip['capacity']),
                     'capacity_uom': trip['capacity_uom'], 'location': node(meta['from_site']), 'working_windows': copy.deepcopy(plan['resources'][0]['working_windows'])}
                resources[rid] = r; plan['resources'].append(r)
            else:
                if resources[rid]['capacity'] != float(trip['capacity']) or resources[rid].get('capacity_uom', trip['capacity_uom']) != trip['capacity_uom']:
                    raise CoherenceError([{'target': rid, 'message': '同一车辆在不同运输中的额定容量不一致'}])
                earlier = [s for s in shipment_rows if str(s['vehicle_id']) == str(trip['vehicle_id'])]
                first = min(earlier, key=lambda s: timestamp(s['ship_at']))
                resources[rid]['location'] = node(first['from_site'])
            line = {'material_id': meta['material_id'], 'location': origin_buffer, 'quantity': meta['quantity']}
            output_buffer = 'assembly' if meta['type'] == 'purchase' else destination_buffer
            task = {'id': tid, 'name': f'入厂运输 · {meta["from_site"]}→{site}', 'kind': 'transport',
                    'quantity': float(trip['load_units']), 'duration_mode': 'batch', 'alternatives': [{'resource_id': rid, 'duration_seconds': duration}],
                    'release_at': depart, 'latest_start_at': depart, 'predecessors': [meta['terminal']] if meta.get('terminal') else [],
                    'inputs': [line], 'outputs': [{**line, 'location': output_buffer}],
                    'from_node': node(meta['from_site']), 'to_node': node(site), 'load_uom': trip['capacity_uom'], 'business_source': source_id,
                    'source_ref': {'module': 'operations', 'role': 'confirmed_inbound', 'source_id': source_id}}
            if tid in group_tasks:
                existing = group_tasks[tid]
                existing['quantity'] += float(trip['load_units'])
                existing['inputs'] += task['inputs']; existing['outputs'] += task['outputs']
                existing['predecessors'] = sorted(set(existing['predecessors'] + task['predecessors']))
            else:
                group_tasks[tid] = task
                plan['tasks'].append(task); transport_ids.append(tid)
            new_predecessors.append(tid)
        if meta['type'] == 'purchase':
            purchase_dependencies[meta['material_id']].update(new_predecessors)
        if meta['type'] == 'factory':
            if 'chain:transfer' in tasks:
                transfer = tasks['chain:transfer']; transfer['name'] = '自制部件收货交接'
                for line in transfer['inputs']:
                    if line['material_id'] == meta['material_id']: line['location'] = destination_buffer
                transfer['predecessors'] = sorted(set(transfer['predecessors'] + new_predecessors))
            else:
                for t in plan['tasks']:
                    if t.get('source_ref', {}).get('unit_index') is not None:
                        for line in t.get('inputs', []):
                            if line['material_id'] == meta['material_id']:
                                line['location'] = destination_buffer
                                t['predecessors'] = sorted(set(t['predecessors'] + new_predecessors))
    for mid, predecessors in purchase_dependencies.items():
        row = purchased_map[mid]
        available = sum(s['quantity'] for s in plan['stock'] if s['location'] == 'assembly' and s['material_id'] == mid)
        if available + 1e-7 < float(row['per_unit']) * config['units']:
            for task in plan['tasks']:
                if task.get('source_ref', {}).get('unit_index') is not None and any(l['material_id'] == mid for l in task.get('inputs', [])):
                    task['predecessors'] = sorted(set(task['predecessors']) | predecessors)
    plan['business_validation'] = {'passed': True, 'status': 'confirmed', 'product_id': bom['product_id'], 'bom_revision': bom['revision'],
        'assembly_site': site, 'checks': checks, 'manual_mappings': manual, 'inbound_tasks': transport_ids,
        'note': '独立BOM与供给/采购/运输关联已核对；源缺项的人工映射明确留痕，仍非现场采集证明'}
