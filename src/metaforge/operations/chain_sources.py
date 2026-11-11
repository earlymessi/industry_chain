"""Read native assembly results and route artifacts without executing optimizers."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .sources import ROOT, assembly_definitions, fingerprint


def csv_rows(path):
    if not path.is_file():
        return []
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def route_catalog(root=ROOT):
    routes = csv_rows(root / 'zhenjie/best_stage2_balanced_vehicle_route_sequence.csv')
    return [{**row, 'id': f'{row["scheme"]}:{row["day"]}:{row["route_id"]}',
             'name': f'第{row["day"]}天 / 路线{row["route_id"]} / 车辆{row["vehicle_id"]} / 仓库{row["start_depot"]}→{row["end_depot"]}'} for row in routes]


def route_source(key, root=ROOT):
    route = next((r for r in route_catalog(root) if r['id'] == key), None)
    if not route:
        raise ValueError('所选配送路线已不存在，请重新选择')
    stops = [s for s in csv_rows(root / 'zhenjie/best_stage2_balanced_vehicle_timeline.csv')
             if all(s[k] == route[k] for k in ('scheme', 'day', 'route_id', 'vehicle_id'))]
    stops.sort(key=lambda s: int(s['stop_order']))
    customers = csv_rows(root / f'zhenjie/customers_day{int(route["day"])}.csv')
    return {'route': route, 'stops': stops, 'customers': customers,
            'version': fingerprint({'route': route, 'stops': stops, 'customers': customers})}


def supply_source(root=ROOT):
    directory = root / 'data/integration'
    def read(name, default):
        path = directory / name
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else default
    data = {'catalog': read('purchased_assembly_parts.json', {'parts': []})['parts'],
            'state': read('purchased_supply_state.json', {'materials': {}, 'deliveries': []})}
    data['version'] = fingerprint(data)
    return data


def process_catalog():
    return [{'id': pid, 'name': d.name, 'minutes': d.standard_time, 'workstations': d.workstation_ids,
             'predecessors': d.predecessors} for pid, d in assembly_definitions().items()]


def assembly_catalog(reader=None):
    rows, messages = [], []
    if reader is None:
        return {'results': [], 'messages': ['组装评估接口未配置，可使用原工艺补排']}
    for count in (6, 8, 10):
        try:
            data = reader(f'/api/evaluation/{count}')
            if data.get('ok') and data.get('has_schedule'):
                for episode in range(1, min(int(data.get('episode_count', 0)), 500) + 1):
                    rows.append({'id': f'{count}:{episode}', 'units': count, 'episode': episode,
                                 'name': f'{count}件 / QMIX评估 {episode}'})
        except (ValueError, OSError, KeyError) as exc:
            messages.append(f'{count}件评估暂不可读：{exc}')
    return {'results': rows, 'messages': messages}


def assembly_source(key, reader):
    if reader is None:
        raise ValueError('组装评估接口未配置')
    try:
        count, episode = map(int, key.split(':'))
    except (ValueError, AttributeError):
        raise ValueError('请选择有效的组装评估结果')
    if count not in (6, 8, 10) or episode < 1:
        raise ValueError('无效的组装评估批量或编号')
    data = reader(f'/api/evaluation/{count}/gantt/{episode}')
    if not data.get('ok') or not data.get('data'):
        raise ValueError('组装评估没有完整甘特，请重新评估或选择原工艺补排')
    return {'id': key, 'units': count, 'rows': data['data'], 'version': fingerprint(data['data'])}
