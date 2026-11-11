"""Synchronize a saved production plan without rewinding the execution clock."""
from __future__ import annotations

import copy
import json

from .coordinator import schedule
from .plans import normalize_plan
from .runtime import advance
from .sources import DATA, production_plan
from .validator import validate

TASK_FIELDS = ('quantity', 'duration_mode', 'alternatives', 'inputs', 'release_at', 'resumable', 'source_priority', 'source_due_at')
ORDER_FIELDS = ('quantity', 'priority', 'due_at')


class NewRunRequired(ValueError):
    """Different work or conflicting local facts must be reviewed as a new run."""


def source_link(plan):
    if plan.get('production_link'):
        return copy.deepcopy(plan['production_link'])
    source = next((s for s in plan.get('source_manifest', []) if s.get('module') == 'production'), None)
    if not source or not plan.get('source_plan_id'):
        return None
    return {'plan_id': plan['source_plan_id'], 'solver_id': plan.get('source_solver') or source.get('solver'),
            'time_unit': source.get('time_unit', 'hours'), 'anchor_at': plan['start_at'],
            'source_version': source.get('sha256'), 'synced_at': None, 'retained_count': 0}


def baseline_fields(row, fields):
    return {key: copy.deepcopy(row.get(key)) for key in fields}


def merge_field(current, original, incoming, label):
    if current == original or current == incoming:
        return copy.deepcopy(incoming)
    if incoming == original:
        return copy.deepcopy(current)  # A confirmed operations change wins over an unchanged source.
    raise NewRunRequired(f'{label}在库内与运维中均被修改，请先确认冲突，或归档后启用新运行')


def legacy_baselines(plan):
    """One-time upgrade of the explicitly identified old standard snapshot only."""
    source = json.loads((DATA / 'production_source.json').read_text(encoding='utf-8'))
    if str(source['id']) != str(plan.get('source_plan_id')):
        return {}, {}
    link = source_link(plan)
    old = production_plan(source, source['machines'], [], link['anchor_at'], solver=link['solver_id'], time_unit=link['time_unit'])
    if old['source_manifest'][0]['sha256'] != link['source_version']:
        return {}, {}
    return {t['name']: t for t in old['tasks']}, {o['name']: o for o in old['orders']}


def synchronize(state, native, now):
    state, transitions = advance(state, now)
    state = copy.deepcopy(state)
    plan = state['plan']; previous_link = source_link(plan)
    if not previous_link or previous_link['plan_id'] != native['source_plan_id']:
        raise NewRunRequired('所选是另一份生产计划；请归档当前运行后启用，不能把不同工单的进度混在一起')
    old_tasks = [t for t in plan['tasks'] if t['kind'] == 'production']
    production_ids = {t['id'] for t in old_tasks}
    old_schedule = {s['task_id']: copy.deepcopy(s) for s in state['schedule']}
    old_by_name = {t['name']: t for t in old_tasks}
    new_by_name = {t['name']: t for t in native['tasks']}
    if len(old_by_name) != len(old_tasks) or set(old_by_name) != set(new_by_name):
        raise NewRunRequired('工单或工艺结构发生变化；当前在制与下游关联不能自动猜测，请归档后启用新运行')
    if plan.get('chain_config'):
        incoming_orders = {o['name']: o for o in native['orders']}
        for order in plan['orders']:
            base = order.get('source_baseline')
            if base and order['name'] in incoming_orders and base.get('quantity') != incoming_orders[order['name']]['quantity']:
                raise NewRunRequired('生产工单数量已变更，请在计划衔接中重新确认部件产出、组装与配送数量')
    identity = {t['id']: old_by_name[t['name']]['id'] for t in native['tasks']}
    # A changed order/operation sequence with identical names is also a process revision.
    for name, incoming in new_by_name.items():
        mapped = [identity[p] for p in incoming.get('predecessors', [])]
        if set(mapped) != set(old_by_name[name].get('predecessors', [])):
            raise NewRunRequired(f'{name}的工艺前置已变更，不能覆盖当前批次的既成工艺')
    fallback_tasks, fallback_orders = legacy_baselines(plan) if any('source_baseline' not in t for t in old_tasks) else ({}, {})
    unchanged = (previous_link.get('source_version') == native['source_manifest'][0]['sha256'] and
                 previous_link.get('solver_id') == native['source_solver'] and previous_link.get('time_unit') == native['source_manifest'][0]['time_unit'] and
                 previous_link.get('anchor_at') == native['start_at'])
    retained, changed = [], []
    frozen = {t['id'] for t in old_tasks if state['tasks'][t['id']]['status'] != 'pending' or state['tasks'][t['id']]['inputs_consumed']}
    for name, incoming in new_by_name.items():
        current = old_by_name[name]
        base = current.get('source_baseline')
        if base is None:
            fallback = fallback_tasks.get(name)
            if fallback is not None:
                base = baseline_fields(fallback, TASK_FIELDS)
            elif unchanged or state['constraint_version'] == 1:
                base = baseline_fields(current, TASK_FIELDS)
            else:
                raise NewRunRequired('该旧运行缺少原输入快照，无法区分本地运维修改与源修改；请归档后重新绑定')
        before = baseline_fields(current, TASK_FIELDS)
        if current['id'] in frozen:
            retained.append(current['id'])
        elif not unchanged:
            for field in TASK_FIELDS:
                value = merge_field(current.get(field), base.get(field), incoming.get(field), f'{current["name"]}/{field}')
                if value is None:
                    current.pop(field, None)
                else:
                    current[field] = value
            if before != baseline_fields(current, TASK_FIELDS):
                changed.append(current['id'])
            state['tasks'][current['id']]['quantity_remaining'] = current['quantity']
            state['tasks'][current['id']]['fraction_remaining'] = 1.0
        current['source_baseline'] = baseline_fields(incoming, TASK_FIELDS)
        current['source_sync_ref'] = copy.deepcopy(incoming['source_ref'])
    if plan.get('scope') == 'production':
        native_orders = {o['name']: o for o in native['orders']}
        for order in plan['orders']:
            incoming = native_orders.get(order['name'])
            if incoming is None:
                raise NewRunRequired('原工单标识发生变化，请作为新运行启用')
            base = order.get('source_baseline') or fallback_orders.get(order['name'])
            if base is None:
                if not unchanged and state['constraint_version'] != 1:
                    raise NewRunRequired('原工单目标快照缺失，请重新绑定')
                base = baseline_fields(order, ORDER_FIELDS)
            if not unchanged:
                if incoming['quantity'] != order['quantity'] and any(t['order_id'] == order['id'] and t['id'] in frozen for t in old_tasks):
                    raise NewRunRequired(f'{order["name"]}已有加工进度，数量变更须作为新批次启用')
                for field in ORDER_FIELDS:
                    order[field] = merge_field(order.get(field), base.get(field), incoming.get(field), f'{order["name"]}/{field}')
            order['source_baseline'] = baseline_fields(incoming, ORDER_FIELDS)
    # Keep actual resource availability and calendars. Source synchronization is not a recovery event.
    for incoming in native['resources']:
        rid = incoming['id']
        if rid not in state['resources']:
            plan['resources'].append(copy.deepcopy(incoming))
            state['resources'][rid] = {**copy.deepcopy(incoming), 'available': True, 'expected_recovery_at': None}
        else:
            state['resources'][rid]['name'] = incoming['name']
            next(r for r in plan['resources'] if r['id'] == rid)['name'] = incoming['name']
    for item in native['stock']:
        key = f'{item["location"]}|{item["material_id"]}'
        if key not in state['inventory']:
            plan['stock'].append(copy.deepcopy(item))
            state['inventory'][key] = item['quantity']
    if not unchanged:
        desired = {identity[s['task_id']]: {**copy.deepcopy(s), 'task_id': identity[s['task_id']]} for s in native['schedule']}
        state['schedule'] = [desired[s['task_id']] if s['task_id'] in desired and s['task_id'] not in frozen else s for s in state['schedule']]
        normalize_plan(plan)
        candidate = schedule(state, now, 'original', routes=state['routes'])
        report = validate(state, candidate, now)
        if not report['passed']:
            raise ValueError('同步后未通过全局校验：' + str(report['violations'][:2]))
        state['schedule'] = candidate['schedule']
        state['routes'] = candidate['routes']
        for row in candidate['schedule']:
            tid = row['task_id']; old = old_schedule.get(tid)
            if tid in production_ids and tid not in frozen and (old is None or old.get('resource_id') != row['resource_id'] or any(abs(old[k] - row[k]) > 1 for k in ('start_at', 'end_at'))):
                if tid not in changed:
                    changed.append(tid)
        state['constraint_version'] += 1
        state['plan_revision'] += 1
    else:
        report = {'passed': True, 'checked_count': 0, 'checks': [], 'violations': [], 'status': 'passed'}
    if plan.get('scope') == 'production':
        plan['name'] = native['name']
    plan['source_solver'] = native['source_solver']
    plan['source_manifest'] = [s for s in plan.get('source_manifest', []) if s.get('module') != 'production']
    plan['source_manifest'].insert(0, copy.deepcopy(native['source_manifest'][0]))
    plan['production_link'] = {**source_link(native), 'synced_at': now, 'retained_count': len(retained)}
    state['production_sync'] = {'at': now, 'source_version': plan['production_link']['source_version'], 'frozen_tasks': retained,
                                 'updated_tasks': changed, 'unchanged': unchanged}
    return state, {'updated_count': len(changed), 'retained_count': len(retained), 'unchanged': unchanged,
                   'validation': report, 'source_version': plan['production_link']['source_version']}, transitions
