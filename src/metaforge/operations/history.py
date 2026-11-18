"""Immutable module results, shared by data centers and operations importers."""
from __future__ import annotations
import copy, json, re, shutil, threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4
from .sources import ROOT, fingerprint

DIRECTORY = ROOT / 'data/module_history'
MODULES = {'production', 'assembly', 'delivery'}
_LOCK = threading.RLock()

def label_time():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime('%Y%m%d %H%M%S')

def record_dir(module, key):
    if module not in MODULES or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', str(key)):
        raise ValueError('无效的历史结果标识')
    directory = DIRECTORY / module / key
    if not directory.resolve().is_relative_to(DIRECTORY.resolve()): raise ValueError('无效的历史目录')
    return directory

def read_record(module, key):
    directory = record_dir(module, key)
    try:
        metadata = json.loads((directory/'record.json').read_text(encoding='utf-8'))
        payload = json.loads((directory/'payload.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc: raise ValueError('历史结果不存在或损坏') from exc
    if fingerprint(payload) != metadata['version']: raise ValueError('历史结果内容已变化，拒绝复用')
    return {**metadata, 'payload':payload}

def records(module):
    if module not in MODULES: raise ValueError('未知数据中心')
    directory=DIRECTORY/module
    result=[]
    if directory.is_dir():
        for path in directory.glob('*/record.json'):
            try:
                row=json.loads(path.read_text(encoding='utf-8'))
                result.append(row)
            except (OSError,ValueError): continue
    return sorted(result,key=lambda r:(not r.get('test_case',False),r['name'],r['created_at']))

def save_record(module, name, payload, *, key=None, metadata=None, dataset=None):
    """Publish metadata last; callers never see a partially copied result."""
    key=key or uuid4().hex; directory=record_dir(module,key)
    def plain(value):
        if hasattr(value,'tolist'): return value.tolist()
        if hasattr(value,'item'): return value.item()
        if isinstance(value,Path): return str(value)
        raise TypeError('不支持的历史结果字段：'+type(value).__name__)
    payload=json.loads(json.dumps(payload,ensure_ascii=False,default=plain,allow_nan=False))
    version=fingerprint(payload)
    with _LOCK:
        if (directory/'record.json').is_file():
            old=read_record(module,key)
            if old['version'] != version: raise ValueError('历史版本不可覆盖，请保存为新结果')
            return {k:v for k,v in old.items() if k!='payload'}
        directory.mkdir(parents=True,exist_ok=True)
        if dataset:
            source=Path(dataset)
            target=directory/'dataset'
            if module=='delivery':
                (target/'zhenjie').mkdir(parents=True,exist_ok=True)
                for artifact in (source/'zhenjie').iterdir():
                    if artifact.is_file() and (artifact.suffix in {'.csv','.png','.html'} and artifact.name not in {'index.html','vrp_lab.html'} or artifact.name in {'operations_result_manifest.json','road_matrices.json','solver_source.py'}):
                        shutil.copy2(artifact,target/'zhenjie'/artifact.name)
                if (source/'data/integration').is_dir(): shutil.copytree(source/'data/integration',target/'data/integration',dirs_exist_ok=True)
        (directory/'payload.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        row={'id':key,'module':module,'name':name,'created_at':datetime.now(timezone.utc).isoformat(), 'version':version, **(metadata or {})}
        temp=directory/'record.pending'
        temp.write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(directory/'record.json')
        return row

def delivery_dataset(key):
    read_record('delivery',key)
    return record_dir('delivery',key)/'dataset'

def assembly_result(key, episode=1):
    record=read_record('assembly',key); payload=record['payload']
    episodes=payload['episodes']
    if episode<1 or episode>len(episodes): raise ValueError('组装历史轮次不存在')
    return {'id':f'history:{key}:{episode}','units':payload['units'],'rows':episodes[episode-1],
            'algorithm':record['algorithm'],'mode':payload.get('mode','saved_qmix'),
            'version':fingerprint({'record':record['version'],'episode':episode}), 'duration_note':payload.get('duration_note','来源记录含运输与服务耗时')}

def archive_assembly(result):
    episodes=result.get('gantt') or []
    if not episodes and not result.get('makespans') and 'avg_reward' not in result: raise ValueError('组装结果为空')
    units=int(result['n_agents'])
    from .chain_sources import mapped_assembly_rows
    reasons=[]
    for rows in episodes:
        try: mapped_assembly_rows(rows,units); reasons.append('')
        except ValueError as exc: reasons.append(str(exc))
    payload={'units':units,'episodes':episodes,'time_unit':'minutes','mode':'saved_qmix','evaluation':result,'compatibility':reasons}
    return save_record('assembly',f'QMIX {units}台 · '+label_time(),payload,
        metadata={'algorithm':'QMIX','units':units,'task_count':len(episodes[0]) if episodes else 0,'result_kind':'schedule' if episodes else 'metrics','episode_count':len(episodes),'compatible':any(not r for r in reasons)})

def archive_delivery(root, name=None, result=None):
    from zhenjie.result_versions import status
    from .chain_sources import csv_rows
    root=Path(root); publication=status(root)
    if not publication['verified']: raise ValueError('配送结果缺少有效的输入与输出版本')
    # The current native directory may be outside a case dataset.
    route_rows=csv_rows(root/'best_stage2_balanced_vehicle_route_sequence.csv')
    timeline=csv_rows(root/'best_stage2_balanced_vehicle_timeline.csv')
    customers=[]
    for path in sorted(root.glob('customers_day*.csv')): customers += csv_rows(path)
    payload={'publication':publication,'result':result or {},'routes':route_rows,'timeline':timeline,'customers':customers}
    key='run-'+publication['run_id']
    # save_record copies only zhenjie plus its independently captured supply snapshot.
    if root.name!='zhenjie': raise ValueError('配送源目录名称无效')
    return save_record('delivery',name or '配送 '+label_time(),payload,key=key,
        metadata={'algorithm':'CCDR-PSO + MO-ALNS','units':sum(float(c.get('demand',0)) for c in customers),'task_count':len(timeline),'route_count':len(route_rows),'compatible':True},dataset=root.parent)

def archive_case(case_id, definition, config, plan, assembly, directory):
    """Freeze all three stage results and their complete, version-pinned handoff configuration."""
    key=definition['name']+'-'+fingerprint({'config':config,'sources':plan['chain_source_versions']})[:12]
    config=copy.deepcopy(config)
    config.update(source_dataset='record:'+key,assembly_id=f'history:{key}:1',confirmed=False)
    by_factory={m['factory_id']:m['sha256'] for m in plan['production_sources']}
    for selection in config['production_sources']: selection['source_version']=by_factory[selection['factory_id']]
    tasks={t['id']:t for t in plan['tasks']}
    for module in ('production','assembly','delivery'):
        slots=[]
        for slot in plan['schedule']:
            task=tasks[slot['task_id']]
            belongs=(task['kind']=='production' if module=='production' else 'process_id' in task.get('source_ref',{}) if module=='assembly' else task['kind'] in ('loading','delivery','return'))
            if belongs: slots.append({'id':task['id'],'name':task['name'],'resource':next(r['name'] for r in plan['resources'] if r['id']==slot['resource_id']),
                'resource_id':slot['resource_id'],'start':(slot['start_at']-plan['start_at'])/60,'end':(slot['end_at']-plan['start_at'])/60})
        payload={'case_id':case_id,'definition':definition,'chain_config':config,'timeline':slots,'units':config['units'],'time_unit':'minutes'}
        if module=='assembly': payload.update(episodes=[assembly['rows']],mode=assembly['mode'],duration_note=assembly['duration_note'],compatibility=[''])
        if module=='production': payload['production_plan_id']=definition['production_plan_id']
        if module=='delivery':
            from .chain_sources import route_source, supply_source
            payload.update(route=route_source(config['route_id'],directory),supply=supply_source(directory))
        metadata={'algorithm':{'production':'Q工单模板 + 计划释放时间','assembly':assembly['algorithm'],'delivery':'CCDR-PSO + MO-ALNS'}[module],
            'units':config['units'],'task_count':len(slots),'compatible':True,'test_case':True,'case_id':case_id,'horizon_days':definition['calendar_days'],'span_minutes':max(s['end'] for s in slots)}
        save_record(module,definition['name'],payload,key=key,metadata=metadata,dataset=directory if module=='delivery' else None)
    return key
