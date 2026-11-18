"""Publish three paired example results; never changes the active operations run.
Run: metaforge-test-env/Scripts/python.exe scripts/seed_chain_examples.py
Existing example production documents are retained, including user recalculations.
"""
from __future__ import annotations
import asyncio, copy, json, shutil, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from bson import ObjectId
from pymongo import MongoClient
from metaforge.utils.mongodb import get_mongo_url, get_mongo_db_name
from metaforge.operations.sources import ROOT, production_plan, select_production_jobs, fingerprint
from metaforge.operations.baselines import make_config, dataset_root
from metaforge.operations.chain import build_chain
from metaforge.operations.chain_sources import route_source, supply_source, assembly_source
from metaforge.operations.distributed import load_production_sources

SPECS = [
 ('chain-demo-normal', 'test1', '短周期：常规生产、采购、组装与配送，约2天。', {'calendar_days':7,'factory_b_release_hours':0,'supplier_delay_minutes':0}),
 ('chain-demo-supply', 'test2', '周计划：工厂B在第6天释放生产，外购同周到货，7天内交付。', {'calendar_days':7,'factory_b_release_hours':120,'supplier_delay_minutes':7200}),
 ('chain-demo-transport', 'test3', '四周计划：工厂B在第4周释放生产，外购按该周备货，齐套后组装配送。', {'calendar_days':28,'factory_b_release_hours':504,'supplier_delay_minutes':30240}),
]
ANCHOR = 1800000000.0

def write(path, value):
 path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

async def publish(db):
 original = db.work_orders.find_one({'_id':ObjectId('693c1376a4c27d96652ad849')})
 if not original: raise ValueError('缺少原始已保存生产计划，无法发布真实来源示范')
 base = ROOT / 'data/operations/baselines/fridge-chain-v1'
 original_definition = json.loads((base/'definition.json').read_text(encoding='utf-8'))
 machines = list(db.machines_layout.find()); materials = list(db.materials_inventory.find())
 async def loader(raw, start):
  doc = db.work_orders.find_one({'_id':ObjectId(raw['plan_id'])})
  offset = float(raw.get('source_zero_offset_hours') or 0)
  p = production_plan(doc, machines, materials, start-offset*3600, solver=raw['solver_id'], time_unit=raw['time_unit'])
  p = select_production_jobs(p, raw.get('job_indices'), offset)
  p['source_manifest'][0]['origin_at'] = start-offset*3600; p['start_at'] = start
  return p
 reports=[]
 for key, name, description, params in SPECS:
  directory=dataset_root(key); directory.mkdir(parents=True,exist_ok=True)
  # The same 5-unit customer demand uses the exact same genuine route publication.
  # Keep its original publication ID and hashes; this is a reference copy, not a new solve.
  for folder in ('data','zhenjie'): shutil.copytree(base/folder,directory/folder,dirs_exist_ok=True)
  oid=ObjectId(fingerprint(key)[:24]); doc=db.work_orders.find_one({'_id':oid})
  if doc is None:
   doc={'_id':oid, 'plan_name':name+' · 部件生产', 'jobs':copy.deepcopy([original['jobs'][8],original['jobs'][11]]),
        'status':'done','created_at':datetime.now(timezone.utc).isoformat(), 'example_case_id':key,
        'example_provenance':{'plan_id':str(original['_id']),'solver':'q','job_indices':[8,11],'time_shift_hours':-30},
        'schedule_results':{'q':copy.deepcopy(original['schedule_results']['q'])}}
   names={j['name']:i for i,j in enumerate(doc['jobs'])}
   rows=[r for r in doc['schedule_results']['q']['gantt_data'] if r.get('job_name') in names]
   for row in rows:
    row['job_id']=names[row['job_name']]; row['start']-=30; row['end']-=30
   for job in doc['jobs']: job['quantity']=5
   doc['schedule_results']['q']['gantt_data']=rows
   doc['schedule_results']['q']['makespan']=max(r['end'] for r in rows)
   db.work_orders.insert_one(doc)
  # These three records are generated fixtures; this migration only updates their own planned releases.
  if doc.get('example_case_id') != key: raise ValueError('示范ID已被其他计划占用')
  doc['plan_name']=name
  for row in doc['schedule_results']['q']['gantt_data']:
   native=next(r for r in original['schedule_results']['q']['gantt_data'] if r['job_name']==row['job_name'] and r['operation_name']==row['operation_name'])
   release=params['factory_b_release_hours'] if row['job_name']==original['jobs'][11]['name'] else 0
   row['start']=native['start']-30+release; row['end']=native['end']-30+release
  rows=doc['schedule_results']['q']['gantt_data']
  makespan=max(r['end'] for r in rows)
  # Drop source-plan metrics, predictions and search history that described the original 44 tasks.
  doc['schedule_results']['q']={'solver_id':'q','name':'Q工单模板 + 计划释放时间','algorithm':'Q工单模板 + 计划释放时间','family':'saved_template',
      'makespan':makespan,'gantt_data':rows,'sequence':[r['job_id'] for r in sorted(rows,key=lambda r:(r['start'],r['job_id']))],
      'metrics':{'makespan':makespan},'meta':{'source_plan_id':str(original['_id']),'source_job_indices':[8,11],'release_offset_hours':params['factory_b_release_hours']}}
  doc['example_provenance']['factory_b_release_hours']=params['factory_b_release_hours']
  db.work_orders.update_one({'_id':oid,'example_case_id':key},{'$set':{k:doc[k] for k in ('plan_name','schedule_results','example_provenance')}})
  write(directory/'production_result.json', {'id':str(oid),'plan_name':doc['plan_name'],'jobs':doc['jobs'],'schedule_results':doc['schedule_results'],'machines':[{k:v for k,v in m.items() if k!='_id'} for m in machines]})
  definition=copy.deepcopy(original_definition)
  definition.update(id=key,name=name,description=description,production_plan_id=str(oid),**params)
  for i,f in enumerate(definition['factories']):
   f['job_indices']=[i]; f['source_zero_offset_hours']=0
  definition['assumptions']=[
   '生产基于原Q算法已保存工单8/11；保留各工单的工序、机器与工时，统一减30小时，并按案例显式增加工厂B的计划释放偏移；每批5件。',
   '组装为原9工序/18工位规则排程的已发布结果，非QMIX；可在组装页面查看同一份45任务甘特。',
   '配送引用完整基线已实际求解的相同5台客户需求和路线，保留原发布版本，不冒充三次新求解。',
   '工厂、BOM、采购、库存与运输为显式案例数据；各环节按同一执行起点映射，启用前重新校验。', description]
  write(directory/'definition.json',definition)
  artifact=directory/'assembly_result.json'
  # Keep previous publication until a replacement has passed validation.
  previous=artifact.read_bytes() if artifact.exists() else None
  if artifact.exists(): artifact.unlink()
  try:
   c=(await make_config(key,loader,ANCHOR))['config']; c['confirmed']=True
   native=await load_production_sources(c,loader,ANCHOR)
   p=build_chain(native,c,supply_source(directory),logistics=route_source(c['route_id'],directory))
   tasks={t['id']:t for t in p['tasks']}
   rows=[]
   for slot in p['schedule']:
    t=tasks[slot['task_id']]
    if t['kind']=='assembly' and 'process_id' in t.get('source_ref', {}):
     ref=t['source_ref']; rows.append([(slot['start_at']-ANCHOR)/60,(slot['end_at']-slot['start_at'])/60,int(slot['resource_id'].split(':')[-1]),ref['unit_index'],ref['process_id']])
   result={'case_id':key,'name':name+' · 组装','units':5,'time_unit':'minutes','algorithm':'原工艺约束规则排程',
           'mode':'saved_rule_example','duration_note':'原9工序标准加工时间；入厂运输与交接单独计时',
           'rows':rows,'production_plan_id':str(oid),'production_version':p['chain_source_versions']['production'],
           'supply_version':p['chain_source_versions']['material']}
   write(artifact,{**result,'version':fingerprint(result)})
   final=(await make_config(key,loader,ANCHOR))
   assert final['summary']['business_validation']['passed'] and final['summary']['time_validation']['passed']
   from metaforge.operations.history import archive_case
   linked=copy.deepcopy(final['config']); linked['confirmed']=True
   verified=build_chain(native,linked,supply_source(directory),assembly_source(linked['assembly_id'],None),route_source(linked['route_id'],directory))
   record_id=archive_case(key,definition,final['config'],verified,assembly_source(linked['assembly_id'],None),directory)
   reports.append({'history_id':record_id,'id':key,'production_plan_id':str(oid),'assembly_tasks':len(rows),'tasks':final['task_count'],
                   'business_checks':len(final['summary']['business_validation']['checks']),'time_checks':len(final['summary']['time_validation']['checks'])})
  except Exception:
   if previous is not None: artifact.write_bytes(previous)
   elif artifact.exists(): artifact.unlink()
   raise
 print(json.dumps(reports,ensure_ascii=False,indent=2))
 return reports

if __name__=='__main__':
 with MongoClient(get_mongo_url('mongodb://localhost:27017'),serverSelectionTimeoutMS=5000) as client:
  asyncio.run(publish(client[get_mongo_db_name('metaforge_mes')]))
