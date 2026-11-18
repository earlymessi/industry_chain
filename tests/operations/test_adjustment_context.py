import copy
from fastapi.testclient import TestClient
from metaforge.operations.adjustments import has_pending_change,adjustment_trigger
from .test_api import client_app,wait_job,NOW


def test_initial_state_and_already_handled_change_do_not_need_an_adjustment():
 assert not has_pending_change({'event_seq':0,'last_event':None})
 current={'event_seq':1,'constraint_version':2,'last_event':{'type':'duration_change','target_id':'T','applied_at':NOW}}
 assert has_pending_change(current) and adjustment_trigger(current)['kind']=='event'
 current['last_adjustment']={'source_event_seq':1,'applied_at':NOW}
 assert not has_pending_change(current) and adjustment_trigger(current)['kind']=='baseline'
 current['event_seq']=2
 assert has_pending_change(current) # same timestamp, different confirmed change


def test_baseline_history_is_explicit_and_event_job_is_bound_to_exact_snapshot():
 app,_=client_app()
 with TestClient(app) as c:
  c.post('/api/operations-tools/plans/activate',json={})
  initial=c.get('/api/operations-tools/current').json()['instance']
  baseline=c.post('/api/operations-tools/adjustments',json={'run_id':initial['run_id']}).json()
  assert baseline['trigger']['kind']=='baseline' and baseline['trigger']['event_seq']==0
  assert wait_job(c,baseline['id'])['trigger']['kind']=='baseline'
  history=c.get('/api/operations-tools/history').json()
  assert history['run_id']==initial['run_id'] and history['adjustments'][0]['trigger']['kind']=='baseline'
  assert c.get('/api/operations-tools/current').json()['instance']['event_seq']==0
  task=initial['tasks'][0];alt=task['alternatives'][0]
  data={'duration_mode':task['duration_mode'],'resource_id':alt['resource_id'],'value':alt.get('unit_seconds',alt.get('duration_seconds'))+60}
  event={'run_id':initial['run_id'],'type':'duration_change','target_id':task['id'],'data':data}
  assert c.post('/api/operations-tools/events',json=event).status_code==200
  current=c.get('/api/operations-tools/current').json()['instance']
  generated=c.post('/api/operations-tools/adjustments',json={'run_id':current['run_id']}).json()
  trigger=generated['trigger']
  assert trigger['kind']=='event' and trigger['event_seq']==1
  assert trigger['constraint_version']==current['constraint_version'] and trigger['target_id']==task['id']
  job=wait_job(c,generated['id']);assert job['status']=='done'
  candidate=job['result']['candidates'][0]
  applied=c.post(f"/api/operations-tools/adjustments/{job['id']}/apply",json={'run_id':current['run_id'],'candidate_id':candidate['id']})
  assert applied.status_code==200,applied.text
  settled=c.get('/api/operations-tools/current').json()['instance']
  assert settled['last_adjustment']['source_event_seq']==1 and not has_pending_change(settled)
  result=c.post('/api/operations-tools/agent/run',json={'run_id':settled['run_id'],'message':'生成调整方案','use_llm':False})
  assert result.status_code==200 and result.json()['status']=='no_changes' and 'adjustment_id' not in result.json()
  data['value']+=60
  assert c.post('/api/operations-tools/events',json=event).status_code==200
  assert has_pending_change(c.get('/api/operations-tools/current').json()['instance'])
