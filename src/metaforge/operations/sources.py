"""Native plan adapters. IDs and capabilities come from their owning modules."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from functools import lru_cache
from pathlib import Path

from .models import new_state

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'data/operations/standard'
UNITS = {'hours': 3600, 'minutes': 60, 'seconds': 1}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(',', ':')).encode()).hexdigest()


def selected_result(doc, solver=None):
    results = doc.get('schedule_results') or {}
    single = doc.get('schedule_result') or {}
    if solver:
        result = results.get(solver) or (single if single.get('solver_id') == solver else None)
        if not result:
            raise ValueError('所选算法没有已保存的排程结果')
        return solver, result
    preferred = doc.get('recommended_solver') or single.get('solver_id')
    if preferred:
        result = results.get(preferred) or single
        if result.get('gantt_data'):
            return preferred, result
    valid = [(key, row) for key, row in results.items() if row.get('gantt_data')]
    if len(valid) == 1:
        return valid[0]
    raise ValueError('请明确选择已保存的算法结果')


def production_plan(doc, machines, materials, start_at, *, solver=None, time_unit='hours'):
    """Import an unstarted simulation copy, keeping the saved Gantt exactly."""
    from metaforge.utils.problem_builder import resolve_task_duration
    if time_unit not in UNITS:
        raise ValueError('请确认原计划时间单位：hours / minutes / seconds')
    factor = UNITS[time_unit]
    sid = str(doc.get('_id') or doc.get('id') or '')
    if not sid:
        raise ValueError('缺少原计划ID')
    solver, result = selected_result(doc, solver)
    jobs = doc.get('jobs') or []
    names = [j['name'] for j in jobs]
    if not jobs or len(names) != len(set(names)):
        raise ValueError('工单为空或重名，无法可靠关联原甘特，请补充唯一工单标识')
    catalog = {int(m['id']): m for m in machines}
    stock = [{'location': 'production', 'material_id': m['id'], 'quantity': m.get('current_stock', 0),
              'name': m.get('name', m['id']), 'unit': m.get('unit', ''),
              'source_ref': {'module': 'production', 'collection': 'materials_inventory', 'id': m['id']}}
             for m in materials]
    plan = {'id': f'production:{sid}:{solver}', 'name': doc.get('plan_name') or sid, 'source': 'production', 'mode': 'simulation',
            'scope': 'production', 'alignment_version': 2, 'source_plan_id': sid, 'source_solver': solver,
            'start_at': start_at, 'orders': [], 'resources': [], 'tasks': [], 'stock': stock, 'supplies': [],
            'route_groups': [], 'routes': [], 'travel_seconds': {}, 'schedule': [],
            'coverage': {'production': 'bound', 'material': 'not_provided', 'assembly': 'unbound', 'delivery': 'unbound'},
            'provenance': '原生产计划的未开工仿真副本；按确认单位平移日期，保留原设备、工序与甘特，不导入旧MES运行进度。',
            'source_manifest': [{'module': 'production', 'collection': 'work_orders', 'id': sid, 'solver': solver,
                                 'time_unit': time_unit, 'sha256': fingerprint({'jobs': jobs, 'gantt': result.get('gantt_data')})}]}
    used = set()
    rows = result.get('gantt_data') or []
    calendar_end = start_at + max(7 * 86400, max((float(r['end']) * factor for r in rows), default=0) + 86400)
    consumed_rows = set()
    for ji, job in enumerate(jobs):
        jid = str(job.get('job_id') or ji)
        oid = f'production:{sid}:job:{jid}'
        quantity = job.get('quantity') or 1
        order = {'id': oid, 'name': job['name'], 'quantity': quantity, 'priority': job.get('priority', 10),
                 'due_at': start_at + float(job['due_date']) * factor if job.get('due_date') is not None else None,
                 'fulfillment_stage': 'production', 'quantity_unit': '件' if job.get('quantity') else '批',
                 'source_ref': {'module': 'production', 'plan_id': sid, 'job_index': ji, 'job_id': job.get('job_id')}}
        previous = None
        op_names = [t.get('name') or f'Op-{oi+1}' for oi, t in enumerate(job['tasks'])]
        for oi, task in enumerate(job['tasks']):
            name = op_names[oi]
            matches = [(ri, row) for ri, row in enumerate(rows) if ri not in consumed_rows and row.get('job_name') == job['name'] and
                       ((row.get('operation_name') == name and op_names.count(name) == 1) or
                        (row.get('operation_id') == oi and (not row.get('operation_name') or row['operation_name'] == name)))]
            if len(matches) != 1:
                raise ValueError(f'{job["name"]}/{name}无法唯一关联已保存甘特，拒绝猜测工序')
            ri, row = matches[0]
            consumed_rows.add(ri)
            options = list(task.get('machine_options') or [task.get('machine_id')])
            if task.get('machine_id') is not None and task['machine_id'] not in options:
                options.insert(0, task['machine_id'])
            if any(mid is None or int(mid) not in catalog for mid in options):
                raise ValueError(f'{name}引用的设备不在原设备目录')
            if int(row['machine_id']) not in [int(m) for m in options]:
                raise ValueError(f'{name}原甘特使用了未授权设备')
            duration = resolve_task_duration(task, job_quantity=job.get('quantity'))
            tid = f'{oid}:op:{oi}'
            ref = {'module': 'production', 'plan_id': sid, 'job_index': ji, 'job_id': job.get('job_id'),
                   'job_name': job['name'],
                   'operation_index': oi, 'operation_name': name, 'solver_job_id': row.get('job_id'), 'time_unit': time_unit}
            alternatives = []
            for mid in options:
                mid = int(mid); used.add(mid)
                durations = task.get('duration_by_machine') or {}
                d = float(durations.get(str(mid), durations.get(mid, duration)))
                alternatives.append({'resource_id': f'production:machine:{mid}', 'duration_seconds': d * factor, 'setup_seconds': 0,
                                     'duration_source': 'duration_by_machine' if durations else '原工序统一工时'})
            entry = {'id': tid, 'name': f'{job["name"]} · {name}', 'kind': 'production', 'order_id': oid, 'quantity': quantity,
                     'quantity_unit': order['quantity_unit'], 'duration_mode': 'batch', 'alternatives': alternatives,
                     'predecessors': [previous] if previous else [], 'release_at': start_at + float(job.get('material_arrival') or 0) * factor,
                     'resumable': bool(task.get('resumable', False)), 'inputs': [], 'outputs': [], 'source_ref': ref,
                     'source_priority': job.get('priority', 10),
                     'source_due_at': order['due_at'],
                     'production_job_id': oid}
            op_quantity = task.get('quantity') or job.get('quantity')
            setup, unit = task.get('setup_time'), task.get('unit_time')
            if setup is not None and unit is not None and op_quantity and not task.get('duration_by_machine'):
                entry['source_time_parameters'] = {'setup_time': setup, 'unit_time': unit, 'quantity': op_quantity, 'unit': time_unit}
                # Keep per-unit semantics only when they reproduce the saved decoder's batch time exactly.
                if abs(float(setup) + float(unit) * op_quantity - duration) < 1e-8 and float(unit) > 0:
                    entry.update(duration_mode='per_unit', quantity=op_quantity, quantity_unit='件')
                    for alt in alternatives:
                        alt.pop('duration_seconds')
                        alt.update(unit_seconds=float(unit) * factor, setup_seconds=float(setup) * factor)
            if oi == 0:
                for line in job.get('bom') or []:
                    if line.get('consume_mode', 'job_start') != 'job_start':
                        raise ValueError(f'{job["name"]}含连续耗料，当前适配器不能把它改成一次扣料')
                    if not job.get('quantity'):
                        raise ValueError(f'{job["name"]}的BOM缺少批量，请先在原计划补齐')
                    mid = line['material_id']
                    if not any(s['material_id'] == mid for s in stock):
                        raise ValueError(f'原物料目录缺少{mid}')
                    entry['inputs'].append({'material_id': mid, 'location': 'production', 'quantity': float(line.get('quantity_per_unit', 1)) * quantity})
                    plan['coverage']['material'] = 'bound'
            plan['tasks'].append(entry)
            plan['schedule'].append({'task_id': tid, 'resource_id': f'production:machine:{int(row["machine_id"])}',
                                     'start_at': start_at + float(row['start']) * factor, 'end_at': start_at + float(row['end']) * factor,
                                     'route_predecessors': [], 'source_ref': ref})
            previous = tid
        order['completion_task_ids'] = [previous]
        plan['orders'].append(order)
    if len(consumed_rows) != len(rows):
        raise ValueError('原甘特存在无法关联或重复的工序')
    for mid in sorted(used):
        m = catalog[mid]
        plan['resources'].append({'id': f'production:machine:{mid}', 'name': m.get('name', f'Machine-{mid}'), 'kind': 'production',
                                  'location': 'production', 'working_windows': [[start_at, calendar_end]],
                                  'calendar_source': '导入副本连续作业日历（需按现场班次确认）',
                                  'source_ref': {'module': 'production', 'collection': 'machines_layout', 'id': mid}})
    from .production_sync import baseline_fields, TASK_FIELDS, ORDER_FIELDS
    for task in plan['tasks']:
        task['source_baseline'] = baseline_fields(task, TASK_FIELDS)
    for order in plan['orders']:
        order['source_baseline'] = baseline_fields(order, ORDER_FIELDS)
    return plan


@lru_cache(maxsize=1)
def assembly_definitions():
    path = ROOT / 'MASA-QMIX/utils/production_line.py'
    spec = importlib.util.spec_from_file_location('_metaforge_operations_assembly_schema', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.ProductionLine.PROCESS_DEFINITIONS


def aligned_standard(start_at):
    """A documented standard binding of actual native definitions, not new equipment."""
    from .coordinator import schedule
    from .validator import validate
    from .plans import normalize_plan
    source = json.loads((DATA / 'production_source.json').read_text(encoding='utf-8'))
    binding = json.loads((DATA / 'binding.json').read_text(encoding='utf-8'))
    plan = production_plan(source, source['machines'], [], start_at, solver=binding['production_solver'], time_unit=binding['production_time_unit'])
    units = int(binding['batch_units'])
    if units != binding['batch_units'] or units < 1:
        raise ValueError('标准组装批量须为正整数')
    native_orders = {o['id']: o for o in plan['orders']}
    batch_id = 'assembly:standard:batch'
    batch_order = {'id': batch_id, 'name': '原生产计划部件 → 组装批次', 'quantity': units, 'priority': 10,
                   'role': 'component', 'fulfillment_stage': 'production', 'due_at': None, 'completion_task_ids': []}
    finals, parts = [], []
    for order in native_orders.values():
        tid = order['completion_task_ids'][0]
        material = f'self:{order["id"]}'
        task = next(t for t in plan['tasks'] if t['id'] == tid)
        task['outputs'].append({'material_id': material, 'location': 'assembly', 'quantity': units,
                                'name': order['name'], 'source_ref': order['source_ref']})
        finals.append(tid)
        parts.append({'material_id': material, 'location': 'assembly', 'quantity': 1})
    for t in plan['tasks']:
        t['order_id'], t['quantity'], t['quantity_unit'] = batch_id, units, '件/批'
    plan['orders'] = [batch_order]
    plan.update(id=binding['id'], name=binding['name'], source='standard', scope='chain', alignment_version=2,
                coverage={k: 'bound' for k in ['production', 'material', 'assembly', 'delivery']},
                provenance='来自原生产计划、MASA组装定义和物流已保存路线的关联标准模拟；新增批量/BOM/日历假设单独列明，非现场实时接管。',
                baseline_parameters=binding['assumptions'])
    plan['source_manifest'][0]['snapshot_path'] = 'data/operations/standard/production_source.json'
    plan['source_manifest'].append({'module': 'assembly', 'path': 'MASA-QMIX/utils/production_line.py',
                                    'sha256': hashlib.sha256((ROOT / 'MASA-QMIX/utils/production_line.py').read_bytes()).hexdigest()})
    plan['source_manifest'].append({'module': 'binding', 'path': 'data/operations/standard/binding.json', 'sha256': fingerprint(binding)})
    definitions = assembly_definitions()
    purchased = json.loads((ROOT / 'data/integration/purchased_assembly_parts.json').read_text(encoding='utf-8'))['parts']
    supply = binding['material_inventory_snapshot']
    materials_by_process = {}
    for part in purchased:
        matches = [pid for pid, d in definitions.items() if d.name == part['workstation'] or (part['workstation'] == '检测打包' and pid == 8)]
        if len(matches) != 1:
            raise ValueError(f'{part["id"]}不能唯一绑定原组装工序')
        materials_by_process.setdefault(matches[0], []).append(part['id'])
        plan['stock'].append({'location': 'assembly', 'material_id': part['id'], 'quantity': float(supply['materials'].get(part['id'], {}).get('on_hand', 0)),
                              'name': part['name'], 'source_ref': {'module': 'assembly', 'path': 'data/integration/purchased_supply_state.json', 'id': part['id']}})
    for pid, definition in definitions.items():
        for ws in definition.workstation_ids:
            plan['resources'].append({'id': f'assembly:workstation:{ws}', 'name': f'{definition.name} · 工位{ws}', 'kind': 'assembly',
                                      'location': 'assembly', 'working_windows': [[start_at, start_at + 7 * 86400]],
                                      'source_ref': {'module': 'assembly', 'path': 'MASA-QMIX/utils/production_line.py', 'id': ws, 'process_id': pid}})
    for unit in range(units):
        for pid, d in definitions.items():
            tid = f'assembly:unit:{unit}:process:{pid}'
            inputs = copy.deepcopy(parts) if pid == 0 else []
            inputs += [{'material_id': mid, 'location': 'assembly', 'quantity': binding['procurement_units_per_fridge']} for mid in materials_by_process.get(pid, [])]
            plan['tasks'].append({'id': tid, 'name': f'整机{unit + 1} · {d.name}', 'kind': 'assembly', 'order_id': batch_id, 'quantity': 1,
                                  'duration_mode': 'per_unit', 'alternatives': [{'resource_id': f'assembly:workstation:{ws}', 'unit_seconds': d.standard_time * 60, 'setup_seconds': 0} for ws in d.workstation_ids],
                                  'predecessors': [f'assembly:unit:{unit}:process:{p}' for p in d.predecessors] or finals[:], 'release_at': start_at,
                                  'resumable': False, 'inputs': inputs, 'outputs': [{'material_id': 'finished:refrigerator', 'location': 'assembly', 'quantity': 1}] if pid == max(definitions) else [],
                                  'source_ref': {'module': 'assembly', 'process_id': pid, 'unit_index': unit, 'path': 'MASA-QMIX/utils/production_line.py'}})
        batch_order['completion_task_ids'].append(f'assembly:unit:{unit}:process:{max(definitions)}')
    log = binding['logistics']; route = log['route']
    if route['start_depot'] != route['end_depot']:
        raise ValueError('该标准绑定只接受原物流闭合路线，不能省略跨仓返程')
    vid, depot = f'logistics:vehicle:{route["vehicle_id"]}', f'logistics:depot:{route["start_depot"]}'
    latest = max(row['end_at'] for row in plan['schedule']) + sum(d.standard_time for d in definitions.values()) * units * 60
    # First 08:00 after conservative full readiness, fixed once at activation.
    day8 = ((latest + 8 * 3600) // 86400) * 86400
    dispatch = day8 if day8 > latest else day8 + 86400
    plan['resources'].append({'id': vid, 'name': f'车辆{route["vehicle_id"]} · 路线{route["route_id"]}', 'kind': 'vehicle',
                              'capacity': log['vehicle_capacity'], 'location': depot, 'working_windows': [[start_at, start_at + 7 * 86400]],
                              'source_ref': {'module': 'logistics', 'id': int(route['vehicle_id']), 'scheme': route['scheme'], 'route_id': route['route_id'], 'day': int(route['day'])}})
    route_id = f'logistics:{route["scheme"]}:day:{route["day"]}:route:{route["route_id"]}'
    load_id, return_id = route_id + ':load', route_id + ':return'
    delivery_ids, delivery_inputs = [], []
    for c in log['customers']:
        cid = int(c['cust_id']); oid = f'logistics:customer:{cid}'; tid = oid + ':delivery'
        qty = float(c['demand'])
        order = {'id': oid, 'name': c['cust_name'], 'customer': c['cust_name'], 'quantity': qty, 'priority': 10,
                 'due_at': None,
                 'source_ref': {'module': 'logistics', 'cust_id': cid, 'day': int(route['day']), 'path': 'zhenjie/customers_day1.csv'}}
        plan['orders'].append(order)
        delivery_ids.append(tid)
        delivery_inputs.append({'material_id': 'finished:refrigerator', 'location': 'assembly', 'quantity': qty})
        plan['tasks'].append({'id': tid, 'name': f'配送 · {c["cust_name"]}', 'kind': 'delivery', 'order_id': oid, 'quantity': qty, 'load_units': qty,
                              'duration_mode': 'batch', 'alternatives': [{'resource_id': vid, 'duration_seconds': 0}], 'release_at': dispatch,
                              'inputs': [{'material_id': 'finished:refrigerator', 'location': '@resource', 'quantity': qty}], 'outputs': [],
                              'to_node': f'logistics:customer:{cid}', 'service_seconds': float(c['service']) * 60,
                              'window_start': dispatch + float(c['tw_start']) * 60, 'window_end': dispatch + float(c['tw_end']) * 60,
                              'window_policy': 'service_start', 'window_hard': log['window_hard'],
                              'window_late_weight': log['window_late_weight'], 'source_ref': order['source_ref']})
    if sum(x['quantity'] for x in delivery_inputs) != units:
        raise ValueError('原物流需求与关联组装批量不一致')
    plan['tasks'].append({'id': load_id, 'name': '原物流路线装车', 'kind': 'loading', 'quantity': units, 'duration_mode': 'batch',
                          'alternatives': [{'resource_id': vid, 'duration_seconds': binding['loading_seconds']}], 'release_at': dispatch,
                          'at_node': depot, 'predecessors': batch_order['completion_task_ids'][:], 'inputs': delivery_inputs,
                          'outputs': [{**x, 'location': '@resource'} for x in delivery_inputs], 'source_ref': {'module': 'binding', 'id': route_id}})
    plan['tasks'].append({'id': return_id, 'name': '原物流车辆返仓', 'kind': 'return', 'quantity': 1, 'duration_mode': 'batch',
                          'alternatives': [{'resource_id': vid, 'duration_seconds': 0}], 'release_at': dispatch,
                          'source_ref': {'module': 'logistics', 'id': route_id}})
    previous = None
    for stop in log['stops']:
        node = depot if stop['node_type'] != 'customer' else f'logistics:customer:{int(float(stop["cust_id"]))}'
        if previous:
            seconds = (float(stop['arrive_min']) - float(previous['finish_min'])) * 60
            if seconds <= 0:
                raise ValueError('原路线缺少有效路段耗时')
            plan['travel_seconds'][f'{previous["node"]}|{node}'] = seconds
        previous = {**stop, 'node': node}
    group = {'id': route_id, 'loading_task': load_id, 'return_task': return_id, 'delivery_tasks': delivery_ids, 'depot': depot, 'vehicle_options': [vid]}
    plan['route_groups'], plan['routes'] = [group], [{**group, 'stops': delivery_ids[:], 'vehicle_id': vid}]
    plan['source_manifest'].append({'module': 'logistics', 'paths': log['source_files'], 'vehicle_id': int(route['vehicle_id']), 'route_id': route['route_id'], 'sha256': fingerprint(log)})
    plan['source_manifest'].append({'module': 'material', 'paths': ['data/integration/purchased_assembly_parts.json', 'data/integration/purchased_supply_state.json'],
                                    'snapshot_path': 'data/operations/standard/binding.json#material_inventory_snapshot',
                                    'sha256': fingerprint({'catalog': purchased, 'stock': supply})})
    calendar_days = int(binding['calendar_days'])
    if not 1 <= calendar_days <= 28:
        raise ValueError('标准日历须为1至28天')
    for resource in plan['resources']:
        resource['working_windows'] = [[start_at, start_at + calendar_days * 86400]]
    plan = normalize_plan(plan)
    state = new_state(plan, start_at)
    candidate = schedule(state, start_at, 'original')
    report = validate(state, candidate, start_at)
    if not report['passed']:
        raise ValueError('关联标准基线未通过校验：' + str(report['violations'][:2]))
    plan['schedule'], plan['routes'] = candidate['schedule'], candidate['routes']
    return plan
