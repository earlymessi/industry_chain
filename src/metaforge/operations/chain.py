"""Compose explicit batch links and handovers; never manufacture a source plan."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

from .coordinator import schedule
from .models import new_state, number as _number, timestamp
from .plans import normalize_plan
from .sources import UNITS, assembly_definitions, fingerprint
from .validator import validate

BEIJING = timezone(timedelta(hours=8))


def number(value, label, minimum=0):
    try:
        return _number(value, label, minimum)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'请填写有效的{label}（不小于{minimum}）') from exc


def calendar(config, start):
    days = int(number(config.get('days', 7), '日历天数', 1))
    if days > 28:
        raise ValueError('执行日历最多28天')
    if config.get('mode') == 'continuous':
        return [[start, start + days * 86400]]
    if config.get('mode') != 'shift':
        raise ValueError('请确认连续作业或每日班次日历')
    begin, end = float(config['begin_hour']), float(config['end_hour'])
    if not 0 <= begin < end <= 24:
        raise ValueError('班次须在同一天内，开始早于结束')
    midnight = datetime.fromtimestamp(start, BEIJING).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return [[max(start, midnight + day * 86400 + begin * 3600), midnight + day * 86400 + end * 3600]
            for day in range(days) if midnight + day * 86400 + end * 3600 > start]


def build_chain(native, config, supply, assembly=None, logistics=None):
    if config.get('confirmed') is not True:
        raise ValueError('请核对并确认批次数量、部件用量、日历和交接参数')
    units = int(number(config.get('units', 0), '组装数量', 1))
    if units != float(config['units']) or units > 100:
        raise ValueError('组装数量须为1至100的整数')
    start = native['start_at']
    windows = calendar(config.get('calendar', {}), start)
    p = copy.deepcopy(native)
    p.update(id='chain:' + fingerprint(config)[:16], name=config.get('name') or '产业链执行计划', source='chain', scope='chain',
             provenance='选定前序结果＋用户确认批次/BOM/日历/交接任务；真实时钟下的执行模拟，不接管原MES进度。')
    p['chain_config'] = copy.deepcopy(config)
    p['time_mapping'] = [{'module': 'production', 'origin_at': start, 'time_unit': p['source_manifest'][0]['time_unit'],
                          'rule': '选定起点＋原甘特相对时间；同步保持此起点'}]
    for r in p['resources']:
        r['working_windows'] = copy.deepcopy(windows)
    original = copy.deepcopy(p['schedule'])
    check = validate(new_state(p, start), {'schedule': original, 'routes': [], 'policy': 'original'}, start)
    if not check['passed']:
        raise ValueError('原生产甘特与已确认日历/库存不兼容：' + str(check['violations'][:2]))
    for order in p['orders']:
        order['role'] = 'component'
    defs = assembly_definitions()
    orders = {o['id']: o for o in p['orders']}
    parts = [r for r in config.get('parts', []) if r.get('enabled', True)]
    if not parts or len({r['order_id'] for r in parts}) != len(parts):
        raise ValueError('至少选择一个不重复的自制部件工单')
    source_by_id = {t['id']: t for t in p['tasks']}
    needed = []
    material_ids = set()
    for row in parts:
        order = orders.get(row['order_id'])
        if order is None:
            raise ValueError('部件工单不属于所选生产计划，请重新关联')
        produced = number(row.get('produced_quantity'), '该工单产出件数', .000001)
        per_unit = number(row.get('per_unit'), '每台自制件用量', .000001)
        pid = int(row.get('process_id', 0))
        if pid not in defs:
            raise ValueError('部件引用未知组装工序')
        if order.get('quantity_unit') == '件' and abs(produced - order['quantity']) > 1e-6:
            raise ValueError(f'{order["name"]}产出件数与原工单数量不符')
        if produced + 1e-6 < per_unit * units:
            raise ValueError(f'{order["name"]}不足以满足{units}台组装需求')
        mid = row.get('material_id') or f'self:{order["id"]}'
        if mid in material_ids:
            raise ValueError('不同自制部件不能使用同一个物料标识，请确认汇总关系')
        material_ids.add(mid)
        terminal = order['completion_task_ids']
        if len(terminal) != 1:
            raise ValueError('自制部件须明确唯一产出工序')
        source_by_id[terminal[0]]['outputs'].append({'material_id': mid, 'location': 'production_output', 'quantity': produced, 'name': row.get('name') or order['name']})
        needed.append({'material_id': mid, 'quantity': per_unit, 'process_id': pid, 'terminal': terminal[0], 'name': row.get('name') or order['name']})
    batch_id, finished = 'chain:assembly:batch', 'chain:finished'
    batch = {'id': batch_id, 'name': '组装成品批次', 'quantity': units, 'due_at': None, 'priority': 10,
             'fulfillment_stage': 'production', 'completion_task_ids': []}
    p['orders'].append(batch)
    supplements = []
    def handover(tid, name, minutes, predecessors, inputs, outputs):
        duration = number(minutes, name + '耗时（分钟）', .001) * 60
        rid = tid + ':resource'
        p['resources'].append({'id': rid, 'name': name + '作业位', 'kind': 'assembly', 'capacity': 1, 'location': 'assembly',
                               'working_windows': copy.deepcopy(windows), 'source_ref': {'module': 'operations', 'role': 'confirmed_handover'}})
        p['tasks'].append({'id': tid, 'name': name, 'kind': 'assembly', 'supplemental': True, 'order_id': batch_id,
                           'quantity': units, 'duration_mode': 'batch', 'alternatives': [{'resource_id': rid, 'duration_seconds': duration}],
                           'release_at': start, 'predecessors': predecessors, 'inputs': inputs, 'outputs': outputs,
                           'source_ref': {'module': 'operations', 'role': 'confirmed_handover'}})
        supplements.append(tid)
        return tid
    transfer = number(config.get('transfer_minutes', 0), '部件交接耗时')
    transfer_id = None
    if transfer:
        lines = [{'material_id': a['material_id'], 'location': 'production_output', 'quantity': a['quantity'] * units} for a in needed]
        transfer_id = handover('chain:transfer', '生产部件转运交接', transfer, sorted({a['terminal'] for a in needed}), lines,
                               [{**x, 'location': 'assembly'} for x in lines])
    # Supplier ETA is anchored to its recorded snapshot, never to each browser refresh.
    purchased = {r['material_id']: r for r in config.get('purchased', []) if r.get('enabled', True)}
    stock_overrides = config.get('stock_overrides', {})
    for item in supply['catalog']:
        mid = item['id']
        qty = stock_overrides.get(mid, supply['state'].get('materials', {}).get(mid, {}).get('on_hand', 0))
        p['stock'].append({'material_id': mid, 'name': item['name'], 'location': 'assembly', 'quantity': number(qty, '外购可用库存'),
                           'source_ref': {'module': 'material', 'id': mid, 'snapshot_at': supply['state'].get('updated_at')}})
    for mid, row in purchased.items():
        if mid not in {a['id'] for a in supply['catalog']} or int(row['process_id']) not in defs:
            raise ValueError('外购件或消耗工序不在原目录')
        number(row.get('per_unit'), '外购件每台用量', .000001)
    arrivals = config.get('arrival_overrides', {})
    for item in supply['state'].get('deliveries', []):
        if item.get('status') not in {'planned', 'on_the_way'} or item.get('material_id') not in purchased:
            continue  # Arrived quantities are already included in on_hand, do not count twice.
        sid = str(item['id'])
        if sid in arrivals:
            at = timestamp(arrivals[sid])
        elif supply['state'].get('updated_at'):
            at = timestamp(supply['state']['updated_at']) + number(item.get('eta_minutes'), '来源ETA') * 60
        else:
            raise ValueError(f'到货批次{sid}缺少固定日期，请补充预计到货时间')
        p['supplies'].append({'id': 'chain:supply:' + sid, 'name': item.get('supplier_name', sid), 'material_id': item['material_id'],
                              'location': 'assembly', 'quantity': number(item.get('quantity'), '到货数量', .000001), 'available_at': at,
                              'source_ref': {'module': 'material', 'id': sid}})
    for item in config.get('additional_supplies', []):
        if item.get('material_id') not in purchased:
            raise ValueError('补充到货必须对应本批已选用的外购件')
        if not item.get('id') or not item.get('available_at'):
            raise ValueError('补充到货需要唯一批次标识和明确到货日期')
        p['supplies'].append({'id': 'chain:manual-supply:' + str(item['id']), 'name': item.get('name') or '运维补充到货',
                              'material_id': item['material_id'], 'location': 'assembly',
                              'quantity': number(item.get('quantity'), '补充到货数量', .000001), 'available_at': timestamp(item['available_at']),
                              'source_ref': {'module': 'operations', 'id': str(item['id']), 'role': 'confirmed_supply'}})
    post = number(config.get('post_minutes', 0), '成品交接耗时')
    if transfer_id:
        first_deps = [transfer_id]
    else:
        first_deps = []
    for pid, d in defs.items():
        for ws in d.workstation_ids:
            p['resources'].append({'id': f'assembly:workstation:{ws}', 'name': f'{d.name} · 工位{ws}', 'kind': 'assembly', 'capacity': 1,
                                   'location': 'assembly', 'working_windows': copy.deepcopy(windows),
                                   'source_ref': {'module': 'assembly', 'process_id': pid, 'id': ws}})
    assembly_tasks = []
    for unit in range(units):
        for pid, d in defs.items():
            tid = f'chain:unit:{unit}:process:{pid}'
            local_parts = [a for a in needed if a['process_id'] == pid]
            dependencies = [f'chain:unit:{unit}:process:{prev}' for prev in d.predecessors]
            if local_parts:
                dependencies += first_deps if transfer_id else [a['terminal'] for a in local_parts]
            inputs = [{'material_id': a['material_id'], 'location': 'assembly' if transfer_id else 'production_output', 'quantity': a['quantity']} for a in local_parts]
            inputs += [{'material_id': mid, 'location': 'assembly', 'quantity': row['per_unit']} for mid, row in purchased.items() if int(row['process_id']) == pid]
            t = {'id': tid, 'name': f'整机{unit + 1} · {d.name}', 'kind': 'assembly', 'order_id': batch_id, 'quantity': 1,
                 'duration_mode': 'per_unit', 'alternatives': [{'resource_id': f'assembly:workstation:{ws}', 'unit_seconds': d.standard_time * 60} for ws in d.workstation_ids],
                 'release_at': start, 'predecessors': sorted(set(dependencies)), 'inputs': inputs,
                 'outputs': [{'material_id': finished, 'location': 'assembly' if post else 'warehouse', 'quantity': 1}] if pid == max(defs) else [],
                 'source_ref': {'module': 'assembly', 'process_id': pid, 'unit_index': unit, 'mode': 'operations_supplement'}}
            p['tasks'].append(t); assembly_tasks.append(t)
            if pid == max(defs):
                batch['completion_task_ids'].append(tid)
    if post:
        post_id = handover('chain:post', '成品转运交接（不重复检测打包）', post, batch['completion_task_ids'][:],
                           [{'material_id': finished, 'location': 'assembly', 'quantity': units}],
                           [{'material_id': finished, 'location': 'warehouse', 'quantity': units}])
        batch['completion_task_ids'] = [post_id]
    source_schedule = []
    if config.get('assembly_mode') == 'saved':
        if not assembly or assembly['units'] != units:
            raise ValueError('组装评估批量与当前组装数量不一致，不能截取或复制评估结果')
        if not config.get('assembly_origin_at'):
            raise ValueError('请明确填写组装评估第0时刻对应的北京时间')
        origin = timestamp(config['assembly_origin_at'])
        factor = UNITS.get(config.get('assembly_time_unit'))
        if factor is None:
            raise ValueError('请确认组装评估时间单位')
        from .chain_sources import mapped_assembly_rows
        slots = []
        for row in mapped_assembly_rows(assembly['rows'], units):
            tid = f'chain:unit:{row["unit"]}:process:{row["process"]}'
            seconds = row['duration'] * factor
            task = next(t for t in assembly_tasks if t['id'] == tid)
            task['alternatives'] = [{'resource_id': f'assembly:workstation:{row["workstation"]}', 'unit_seconds': seconds}]
            task['source_ref'].update(mode=assembly.get('mode', 'saved_qmix'), evaluation_id=assembly['id'], algorithm=assembly.get('algorithm', 'QMIX'), duration_note=assembly.get('duration_note', '来源记录含其运输/服务耗时'))
            slots.append({'task_id': tid, 'resource_id': task['alternatives'][0]['resource_id'],
                          'start_at': origin + row['offset'] * factor,
                          'end_at': origin + (row['offset'] + row['duration']) * factor})
        validate_assembly_slots(assembly_tasks, slots)
        source_schedule = slots
        p['schedule'] += slots
        p['source_manifest'].append({'module': 'assembly', 'id': assembly['id'], 'sha256': assembly['version'], 'time_unit': config['assembly_time_unit']})
        p['time_mapping'].append({'module': 'assembly', 'origin_at': origin, 'time_unit': config['assembly_time_unit'], 'rule': '用户确认评估零点；齐套或资源冲突引起的调整单独列出'})
    elif config.get('assembly_mode') == 'supplement':
        p['source_manifest'].append({'module': 'assembly', 'path': 'MASA-QMIX/utils/production_line.py',
                                     'sha256': fingerprint([(pid, d.name, d.standard_time, d.workstation_ids, d.predecessors) for pid, d in defs.items()]), 'mode': 'operations_supplement'})
        p['time_mapping'].append({'module': 'assembly', 'rule': '按部件/外购齐套、原工艺、班次与资源空档补排；不复用无关评估'})
    else:
        raise ValueError('请选择已保存组装评估或原工艺补排')
    if config.get('delivery_mode') == 'saved':
        if logistics is None:
            raise ValueError('请选择配送路线')
        add_route(p, config, logistics, batch, finished, windows)
    elif config.get('delivery_mode') != 'unbound':
        raise ValueError('请选择配送路线，或明确标记配送待绑定')
    p['coverage'].update(material='bound',
                         assembly='bound', delivery='bound' if logistics else 'unbound')
    versions = {'production': native['source_manifest'][0]['sha256'], 'material': supply['version'],
                'assembly': p['source_manifest'][-1].get('sha256') if not logistics else next(s['sha256'] for s in p['source_manifest'] if s['module'] == 'assembly')}
    if logistics:
        versions['logistics'] = logistics['version']
    p['source_manifest'].append({'module': 'material', 'sha256': supply['version'], 'snapshot_at': supply['state'].get('updated_at')})
    p['chain_source_versions'] = versions
    if config.get('coherence_version') == 1:
        from .coherence import apply_coherence
        apply_coherence(p, config, supply, logistics)
    else:
        p['business_validation'] = {'passed': False, 'status': 'legacy', 'note': '仅完成技术排程校验，尚未确认独立BOM、工厂、采购与入厂运输关系'}
    p = normalize_plan(p)
    candidate = schedule(new_state(p, start), start, 'original')
    actual = {s['task_id']: s for s in candidate['schedule']}
    for row in original:
        if any(abs(actual[row['task_id']][k] - row[k]) > 1e-4 for k in ('start_at', 'end_at')) or actual[row['task_id']]['resource_id'] != row['resource_id']:
            raise ValueError('衔接条件会改变原生产甘特，请先在生产模块确认新排程')
    report = validate(new_state(p, start), candidate, start)
    if not report['passed']:
        raise ValueError('全链路校验失败：' + str(report['violations'][:2]))
    changes = [{'task_id': row['task_id'], 'name': next(t['name'] for t in assembly_tasks if t['id'] == row['task_id']),
                'original_start_at': row['start_at'], 'start_at': actual[row['task_id']]['start_at'],
                'original_end_at': row['end_at'], 'end_at': actual[row['task_id']]['end_at']} for row in source_schedule
               if any(abs(row[k] - actual[row['task_id']][k]) > 1e-4 for k in ('start_at', 'end_at'))]
    p['schedule'], p['routes'] = candidate['schedule'], candidate['routes']
    p['source_schedule'] = source_schedule
    from .temporal import temporal_report
    p['time_validation'] = temporal_report(p)
    p['chain_summary'] = {'supplemental_tasks': supplements, 'assembly_changes': changes, 'units': units,
                          'delivery_bound': bool(logistics), 'source_versions': versions,
                          'business_validation': p['business_validation'], 'time_validation': p['time_validation'],
                          'note': '规则补排验证可行性，不宣称联合最优；执行仍为模拟'}
    return p


def validate_assembly_slots(tasks, slots):
    rows = {s['task_id']: s for s in slots}
    for t in tasks:
        r = rows[t['id']]
        for dep in t['predecessors']:
            if dep in rows and rows[dep]['end_at'] > r['start_at'] + 1e-5:
                raise ValueError('原组装评估不满足当前工艺前置，不能直接导入')
    for i, a in enumerate(slots):
        for b in slots[i + 1:]:
            if a['resource_id'] == b['resource_id'] and min(a['end_at'], b['end_at']) > max(a['start_at'], b['start_at']) + 1e-5:
                raise ValueError('原组装评估存在工位重叠')


def add_route(p, config, source, batch, finished, windows):
    route, stops = source['route'], source['stops']
    if len(stops) < 3 or stops[0]['node_type'] != 'depot_start' or stops[-1]['node_type'] != 'depot_end':
        raise ValueError('路线缺少完整出发、客户或到仓时间')
    date = datetime.strptime(config['delivery_date'], '%Y-%m-%d').replace(tzinfo=BEIJING)
    origin = timestamp(config['delivery_origin_at']) if config.get('delivery_origin_at') is not None else date.replace(hour=8).timestamp()
    if datetime.fromtimestamp(origin, BEIJING).date() != date.date():
        raise ValueError('配送日期与配送时间原点不一致，请重新确认映射')
    dispatch = origin + float(route['start_time_min']) * 60
    vehicle = f'logistics:vehicle:{route["vehicle_id"]}'
    depot, end_depot = f'logistics:depot:{route["start_depot"]}', f'logistics:depot:{route["end_depot"]}'
    cap = number(config.get('vehicle_capacity'), '确认车辆额定容量', .000001)
    if batch['quantity'] > cap:
        raise ValueError('组装批量超过所选车辆容量，请先确认拆批或另一条路线')
    p['resources'].append({'id': vehicle, 'name': f'车辆{route["vehicle_id"]}', 'kind': 'vehicle', 'capacity': cap,
                           'capacity_uom': config.get('dispatch_uom') or '整机件', 'location': depot, 'working_windows': copy.deepcopy(windows), 'source_ref': {'module': 'logistics', 'id': route['vehicle_id']}})
    rid = 'chain:route:' + source['route']['id']; load, ret = rid + ':load', rid + ':return'
    customer_map = {str(int(float(c['cust_id']))): c for c in source['customers']}
    delivery_ids, quantity = [], 0
    commitments = config.get('customer_commitments', {})
    previous = None
    for stop in stops:
        is_customer = stop['node_type'] == 'customer'
        node = f'logistics:customer:{int(float(stop["cust_id"]))}' if is_customer else depot if previous is None else end_depot
        if previous is not None:
            seconds = (float(stop['arrive_min']) - float(previous['finish_min'])) * 60
            if seconds <= 0:
                raise ValueError('原路线缺少有效路段耗时，不能用距离猜测')
            p['travel_seconds'][f'{previous_node}|{node}'] = seconds
        if is_customer:
            cid = str(int(float(stop['cust_id'])))
            customer = customer_map.get(cid)
            if customer is None:
                raise ValueError('路线客户不在当日需求目录')
            qty = number(customer.get('demand'), '客户需求', .000001); quantity += qty
            oid, tid = rid + ':customer:' + cid, rid + ':delivery:' + cid
            p['orders'].append({'id': oid, 'name': customer.get('cust_name') or cid, 'quantity': qty, 'priority': 10,
                                'due_at': timestamp(commitments[cid]) if commitments.get(cid) else None,
                                'source_ref': {'module': 'logistics', 'id': cid}})
            task = {'id': tid, 'name': '配送 · ' + (customer.get('cust_name') or cid), 'kind': 'delivery', 'order_id': oid,
                    'quantity': qty, 'load_units': qty, 'duration_mode': 'batch', 'alternatives': [{'resource_id': vehicle, 'duration_seconds': 0}],
                    'release_at': dispatch, 'to_node': node, 'predecessors': [],
                    'inputs': [{'material_id': finished, 'location': '@resource', 'quantity': qty}], 'outputs': [],
                    'service_seconds': number(customer.get('service'), '客户服务耗时') * 60,
                    'window_start': origin + float(customer['tw_start']) * 60, 'window_end': origin + float(customer['tw_end']) * 60,
                    'window_policy': 'service_start', 'window_hard': bool(config.get('customer_windows_hard', False)), 'window_late_weight': 50,
                    'source_ref': {'module': 'logistics', 'id': cid, 'route_id': route['id']}}
            if not delivery_ids:
                task['latest_start_at'] = dispatch  # Fixed original departure; no silent postponement.
            p['tasks'].append(task); delivery_ids.append(tid)
        previous, previous_node = stop, node
    if abs(quantity - batch['quantity']) > 1e-6:
        raise ValueError(f'路线客户合计需求{quantity:g}，与本批组装{batch["quantity"]:g}不一致，请确认批次分配')
    duration = number(config.get('loading_minutes'), '装车分钟数', .001) * 60
    lines = [{'material_id': finished, 'location': 'warehouse', 'quantity': quantity}]
    p['tasks'].append({'id': load, 'name': '成品出库装车', 'kind': 'loading', 'quantity': quantity, 'duration_mode': 'batch',
                       'alternatives': [{'resource_id': vehicle, 'duration_seconds': duration}], 'release_at': p['start_at'],
                       'latest_end_at': dispatch, 'predecessors': batch['completion_task_ids'][:], 'at_node': depot,
                       'inputs': lines, 'outputs': [{**x, 'location': '@resource'} for x in lines],
                       'source_ref': {'module': 'operations', 'role': 'confirmed_loading'}})
    p['tasks'].append({'id': ret, 'name': '车辆到达终点仓', 'kind': 'return', 'quantity': 1, 'duration_mode': 'batch',
                       'alternatives': [{'resource_id': vehicle, 'duration_seconds': 0}], 'release_at': dispatch,
                       'predecessors': [], 'inputs': [], 'outputs': [], 'source_ref': {'module': 'logistics', 'id': route['id']}})
    p['route_groups'].append({'id': rid, 'loading_task': load, 'delivery_tasks': delivery_ids, 'return_task': ret,
                               'depot': depot, 'end_depot': end_depot, 'vehicle_options': [vehicle]})
    p['routes'].append({'id': rid, 'vehicle_id': vehicle, 'stops': delivery_ids, 'loading_task': load,
                        'depot': depot, 'end_depot': end_depot, 'return_task': ret})
    batch['role'] = 'component'
    p['source_manifest'].append({'module': 'logistics', 'id': route['id'], 'sha256': source['version'], 'day_date': config['delivery_date']})
    p['time_mapping'].append({'module': 'logistics', 'origin_at': origin, 'departure_at': dispatch,
                              'rule': '来源分钟偏移映射到明确的配送时间原点；发车和窗口不随上游延期平移'})
