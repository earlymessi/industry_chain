"""Historical snapshots must survive new calculations and retain complete cross-stage contracts."""
import copy, json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from metaforge.operations import history
from metaforge.operations.api import create_router
from metaforge.operations.service import OperationsService
from metaforge.operations.store import MemoryStore
from metaforge.operations.baselines import dataset_root
from metaforge.operations.chain_sources import assembly_source
from .test_source_alignment import Collection
from .test_chain_examples import IDS,doc,NOW


def test_snapshots_are_immutable_verified_and_cannot_escape_history_directory(tmp_path,monkeypatch):
 monkeypatch.setattr(history,'DIRECTORY',tmp_path)
 payload={'episodes':[[[0,8,0,0,0]]],'units':1}
 a=history.save_record('assembly','old',payload,key='first')
 payload['episodes'][0][0][0]=99
 b=history.save_record('assembly','new',payload,key='second')
 assert history.read_record('assembly',a['id'])['payload']['episodes'][0][0][0]==0
 assert history.read_record('assembly',b['id'])['payload']['episodes'][0][0][0]==99
 with pytest.raises(ValueError,match='不可覆盖'):history.save_record('assembly','bad',payload,key='first')
 with pytest.raises(ValueError):history.record_dir('assembly','../outside')
 with pytest.raises(ValueError):history.record_dir('wrong','valid')
 (tmp_path/'assembly/first/payload.json').write_text('{}',encoding='utf-8')
 with pytest.raises(ValueError,match='已变化'):history.read_record('assembly','first')


def test_native_assembly_preserves_each_calculation_and_all_episodes(tmp_path,monkeypatch):
 monkeypatch.setattr(history,'DIRECTORY',tmp_path)
 rows=assembly_source('example:chain-demo-normal',None)['rows']
 result={'n_agents':5,'model_num':'native-evaluation','gantt':[rows,copy.deepcopy(rows)],'makespans':[10,20],'avg_reward':1.0}
 a=history.archive_assembly(result);b=history.archive_assembly(result)
 assert a['id']!=b['id'] and len(history.records('assembly'))==2
 assert history.assembly_result(a['id'],2)['rows']==rows
 metrics=history.archive_assembly({'n_agents':5,'makespans':[20],'avg_reward':2,'scene_mode':'joint'})
 assert metrics['result_kind']=='metrics' and not metrics['compatible']


def test_test1_test2_test3_have_distinct_real_plan_spans_and_consistent_names():
 for module in ('production','assembly','delivery'):
  rows=[r for r in history.records(module) if r.get('test_case')]
  assert [r['name'] for r in rows]==['test1','test2','test3']
  spans=[r['span_minutes']/1440 for r in rows]
  assert 0<spans[0]<2 and 5<spans[1]<7 and 21<spans[2]<28
  for row in rows:
   payload=history.read_record(module,row['id'])['payload']
   assert payload['definition']['name']==row['name']
   assert len(payload['chain_config']['procurement_orders'])==10
   assert len(payload['chain_config']['assembly_bom']['lines'])==12


def test_all_three_data_centers_prepare_the_same_complete_verified_baseline_without_replacing_current_run():
 documents=Collection([doc(k) for k in IDS])
 app=FastAPI();app.include_router(create_router(OperationsService(MemoryStore(),clock=lambda:NOW),documents,Collection(doc(IDS[0])['machines']),Collection([])))
 with TestClient(app) as client:
  for module in ('production','assembly','delivery'):
   records=client.get('/api/operations-tools/data-center/'+module).json()['records']
   for row in [r for r in records if r.get('test_case')]:
    detail=client.get(f"/api/operations-tools/data-center/{module}/{row['id']}")
    assert detail.status_code==200,detail.text
    prepared=client.post(f"/api/operations-tools/data-center/{module}/{row['id']}/prepare",json={'start_at':NOW+1234})
    assert prepared.status_code==200,prepared.text
    config=prepared.json()['config'];assert not config['confirmed']
    assert config['source_dataset']=='record:'+row['id']
    assert config['assembly_id']==f"history:{row['id']}:1"
    config['confirmed']=True
    p=client.post('/api/operations-tools/plans/chain/preview',json=config)
    assert p.status_code==200,p.text
    assert p.json()['can_activate'] and len(p.json()['plan']['tasks'])==66
    assert p.json()['summary']['assembly_changes']==[]
   assert client.get('/api/operations-tools/current').json()['instance'] is None
  row=history.records('assembly')[0]
  documents.rows[0]['jobs'][0]['priority']+=1
  changed=client.post(f"/api/operations-tools/data-center/assembly/{row['id']}/prepare",json={'start_at':NOW+1234})
  assert changed.status_code in (409,422) and '变化' in changed.json()['detail']


def test_delivery_archive_keeps_old_inputs_outputs_and_maps_after_later_run(tmp_path,monkeypatch):
 from zhenjie.result_versions import capture_inputs,publish,status
 monkeypatch.setattr(history,'DIRECTORY',tmp_path/'history')
 root=tmp_path/'source/zhenjie';root.mkdir(parents=True)
 contents={'customers_day1.csv':'cust_id,demand\n1,5\n',
  'best_stage2_balanced_vehicle_route_sequence.csv':'scheme,day,route_id,vehicle_id\nS,1,1,1\n',
  'best_stage2_balanced_vehicle_timeline.csv':'node_type,day,cust_id\ncustomer,1,1\n',
  'best_stage2_routes_map.html':'<p>old-map</p>', 'app.py':'not-an-artifact'}
 for name,content in contents.items():(root/name).write_text(content,encoding='utf-8')
 publish(root,capture_inputs(root),{'T':1})
 saved=history.archive_delivery(root,name='first')
 snapshot=history.delivery_dataset(saved['id'])/'zhenjie'
 (root/'customers_day1.csv').write_text('cust_id,demand\n1,99\n',encoding='utf-8')
 (root/'best_stage2_routes_map.html').write_text('new-map',encoding='utf-8')
 assert status(snapshot)['verified']
 assert (snapshot/'customers_day1.csv').read_text(encoding='utf-8')==contents['customers_day1.csv']
 assert (snapshot/'best_stage2_routes_map.html').read_text(encoding='utf-8')==contents['best_stage2_routes_map.html']
 assert not (snapshot/'app.py').exists()
 with pytest.raises(ValueError,match='有效'):history.archive_delivery(root)
