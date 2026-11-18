"""A demo round reloads an immutable case, never edits the old execution facts."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

from .models import timestamp

TIME_FIELDS = {'start_at', 'end_at', 'release_at', 'due_at', 'available_at', 'window_start', 'window_end',
               'latest_start_at', 'latest_end_at', 'source_due_at', 'origin_at', 'departure_at', 'anchor_at',
               'original_start_at', 'original_end_at', 'assembly_origin_at', 'delivery_origin_at', 'arrive_at', 'service_start_at', 'deadline_at', 'expected_arrival_at', 'ready_at', 'ship_at', 'arrival_at', 'purchase_at'}


def rebase_case(seed, start):
    if seed.get('mode') != 'simulation':
        raise ValueError('只有模拟案例可以重新加载，现场实例不能清空进度')
    seed = copy.deepcopy(seed)
    config = seed.get('chain_config') or {}
    logistics = next((m for m in seed.get('time_mapping', []) if m.get('module') == 'logistics'), {})
    if config.get('delivery_mode') == 'saved' and not config.get('delivery_origin_at') and logistics.get('origin_at') is not None:
        config['delivery_origin_at'] = logistics['origin_at']
    original = timestamp(seed['start_at']); delta = start - original
    zone = timezone(timedelta(hours=8))
    days = (datetime.fromtimestamp(start, zone).date() - datetime.fromtimestamp(original, zone).date()).days
    def shift(value, key=None):
        if key in TIME_FIELDS and value is not None and value != '':
            return timestamp(value) + delta
        if key == 'working_windows':
            return [[timestamp(a) + delta, timestamp(b) + delta] for a, b in value]
        if key == 'delivery_date' and value:
            return (datetime.strptime(value, '%Y-%m-%d') + timedelta(days=days)).strftime('%Y-%m-%d')
        if key in {'arrival_overrides', 'customer_commitments'} and isinstance(value, dict):
            return {k: timestamp(v) + delta if v not in (None, '') else v for k, v in value.items()}
        if isinstance(value, dict):
            result = {k: shift(v, k) for k, v in value.items()}
            if result.get('delivery_origin_at') is not None:
                result['delivery_date'] = datetime.fromtimestamp(timestamp(result['delivery_origin_at']), zone).date().isoformat()
            return result
        if isinstance(value, list):
            return [shift(v) for v in value]
        return copy.deepcopy(value)
    plan = shift(seed)
    plan['case_replay'] = {'original_start_at': original, 'start_at': start, 'shift_seconds': delta,
                           'note': '新一轮模拟整体平移案例日期；原业务订单及实际库存不变'}
    return plan


def archive_summary(state):
    return {'run_id': state['run_id'], 'name': state['plan']['name'], 'activated_at': state.get('activated_at'),
            'archived_at': state.get('archived_at'), 'reason': state.get('archive_reason'), 'tasks': len(state['tasks']),
            'completed': sum(t['status'] == 'completed' for t in state['tasks'].values())}
