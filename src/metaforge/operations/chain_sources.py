"""Read native assembly results and route artifacts without executing optimizers."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .sources import ROOT, assembly_definitions, fingerprint
from .models import number


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
    from zhenjie.result_versions import status
    publication = status(root / 'zhenjie')
    return {'route': route, 'stops': stops, 'customers': customers, 'publication': publication,
            'version': fingerprint({'route': route, 'stops': stops, 'customers': customers, 'publication': publication})}


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


def mapped_assembly_rows(rows, units):
    """Share exactly the same compatibility checks between picker and importer."""
    defs = assembly_definitions()
    process_by_ws = {ws: pid for pid, d in defs.items() for ws in d.workstation_ids}
    mapped, found = [], set()
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) not in (4, 5):
            raise ValueError('组装甘特须包含开始/持续/工位/产品，可附明确工序ID')
        offset, duration, ws, unit = row[:4]
        if int(ws) != ws or int(unit) != unit or int(ws) not in process_by_ws or not 0 <= int(unit) < units:
            raise ValueError('组装评估的工位/产品标识无法对应原工艺')
        pid = process_by_ws[int(ws)]
        if len(row) == 5 and (int(row[4]) != row[4] or int(row[4]) != pid):
            raise ValueError('组装评估的明确工序ID与当前工位能力不一致，请使用原工艺补排或适配来源模型')
        key = (int(unit), pid)
        if key in found:
            raise ValueError('组装评估的工位能力与当前9工序定义不一致，无法唯一映射；请用原工艺补排，不复制旧模型任务')
        found.add(key)
        mapped.append({'unit': int(unit), 'process': pid, 'workstation': int(ws),
                       'offset': number(offset, '评估开始偏移', 0), 'duration': number(duration, '评估持续时间', .000001)})
    if found != {(unit, pid) for unit in range(units) for pid in defs}:
        raise ValueError('组装评估未覆盖当前产品的全部9道工序')
    by_key = {(r['unit'], r['process']): r for r in mapped}
    for row in mapped:
        for predecessor in defs[row['process']].predecessors:
            previous = by_key[(row['unit'], predecessor)]
            if previous['offset'] + previous['duration'] > row['offset'] + 1e-5:
                raise ValueError('原组装评估不满足当前工艺前置，不能直接导入')
    for i, row in enumerate(mapped):
        for other in mapped[i + 1:]:
            if row['workstation'] == other['workstation'] and min(row['offset'] + row['duration'], other['offset'] + other['duration']) > max(row['offset'], other['offset']) + 1e-5:
                raise ValueError('原组装评估存在工位重叠')
    return mapped


def assembly_catalog(reader=None):
    rows, messages = [], []
    from .baselines import list_baselines
    from .history import records, read_record
    archived = records('assembly')
    archived_cases = {r.get('case_id') for r in archived if r.get('test_case')}
    for case in list_baselines():
        if not case.get('assembly_id') or case['id'] in archived_cases: continue
        source = assembly_source(case['assembly_id'], None)
        rows.append({'id': source['id'], 'units': source['units'], 'name': case['name'] + ' / 规则排程', 'compatible': True, 'algorithm': source['algorithm'], 'case_id': case['id']})
    archived_rows=set()
    for record in archived:
        try: payload = read_record('assembly', record['id'])['payload']
        except ValueError as exc:
            messages.append(record['name']+'：'+str(exc)); continue
        for episode, episode_rows in enumerate(payload['episodes'], 1):
            archived_rows.add((payload['units'],fingerprint(episode_rows)))
            reason = ''
            try: mapped_assembly_rows(episode_rows, payload['units'])
            except ValueError as exc: reason = str(exc)
            rows.append({'id':f"history:{record['id']}:{episode}",'units':payload['units'],'episode':episode,'name':record['name'] + f' / 第{episode}轮','compatible':not reason,'reason':reason,'record_id':record['id'], 'case_id':record.get('case_id')})
    if reader is None:
        return {'results': rows, 'messages': ['QMIX评估接口未配置；示范结果独立可读']}
    for count in (6, 8, 10):
        try:
            data = reader(f'/api/evaluation/{count}')
            if data.get('ok') and data.get('has_schedule'):
                for episode in range(1, min(int(data.get('episode_count', 0)), 500) + 1):
                    key = f'{count}:{episode}'
                    row = {'id': key, 'units': count, 'episode': episode, 'name': f'{count}台 / QMIX评估 {episode}',
                           'compatible': False, 'reason': ''}
                    try:
                        source = assembly_source(key, reader)
                        if (count,fingerprint(source['rows'])) in archived_rows: continue
                        mapped_assembly_rows(source['rows'], count)
                        row['compatible'] = True
                    except (ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
                        row['reason'] = str(exc)
                    rows.append(row)
        except (ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
            messages.append(f'{count}台评估暂不可读：{exc}')
    return {'results': rows, 'messages': messages}


def assembly_source(key, reader):
    if isinstance(key,str) and key.startswith('history:'):
        from .history import assembly_result
        try:
            _,record_id,episode=key.split(':')
            return assembly_result(record_id,int(episode))
        except (ValueError,TypeError) as exc: raise ValueError('请选择有效的组装历史结果：'+str(exc)) from exc
    if isinstance(key, str) and key.startswith('example:'):
        from .baselines import dataset_root
        directory = dataset_root(key.removeprefix('example:'))
        path = directory / 'assembly_result.json'
        if not path.is_file(): raise ValueError('示范组装结果尚未发布')
        data = json.loads(path.read_text(encoding='utf-8'))
        expected = data.pop('version')
        if fingerprint(data) != expected: raise ValueError('示范组装结果校验失败，请重新发布案例')
        mapped_assembly_rows(data['rows'], data['units'])
        return {**data, 'id': key, 'version': expected}
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
