"""The operations agent reasons over tool facts and never silently submits changes."""
import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from metaforge.operations.assistant import assist
from metaforge.operations.models import new_state
from .fixtures import prepare_legacy_plan
from .test_api import client_app, wait_job, NOW


def state():return new_state(prepare_legacy_plan(NOW),NOW)


def test_inspection_uses_actual_tools_and_leaves_the_execution_untouched():
 s=state();before=copy.deepcopy(s)
 result=assist(s,'巡检当前计划',NOW,False)
 assert result['agent']['id']=='operations' and result['intent']=='inspect'
 assert result['status']=='analyzed' and not result['prepared_event']['missing']
 assert result['prepared_event']['draft'] is None and result['plan_request'] is None
 assert [t['tool'] for t in result['trace']]==['operations.query_state','operations.analyze_impact']
 assert all(t['ok'] for t in result['trace']) and s==before
 assert not result['llm_used'] and result['checked_at']==NOW


def test_unconfirmed_fault_with_plan_request_produces_only_a_reviewable_draft():
 s=state();result=assist(s,'M1 故障20分钟，请生成调整方案',NOW,False)
 assert result['status']=='awaiting_confirmation'
 assert result['prepared_event']['draft']['data']['expected_recovery_at']==NOW+1200
 assert result['requested_plan_after_confirmation'] and result['plan_request'] is None
 assert s['event_seq']==0 and s['resources']['M1']['available']


def test_ambiguous_or_missing_object_cannot_compute_a_plan_for_a_guessed_change():
 for message in ['一台机器故障20分钟，请重排','M1 和 M2 故障20分钟，生成方案','车辆少了一辆，帮我重排']:
  result=assist(state(),message,NOW,False)
  assert result['status']=='needs_information'
  assert result['prepared_event']['draft'] is None and result['plan_request'] is None
  assert result['prepared_event']['missing']


def test_readonly_hypothetical_does_not_turn_into_a_fault_or_solver_command():
 for message in ['如果 M1 故障，会影响什么？生成方案？','不要登记 M1 故障，只分析影响','M1 修好了吗？']:
  s=state();result=assist(s,message,NOW,False)
  assert result['intent']=='impact' and result['prepared_event']['draft'] is None
  assert result['plan_request'] is None and s['event_seq']==0


def test_machine_identity_does_not_match_a_shorter_prefix():
 s=state();s['resources']['M10']={**s['resources']['M1'],'id':'M10','name':'M10'}
 result=assist(s,'M10 故障20分钟',NOW,False)
 assert result['prepared_event']['draft']['target_id']=='M10'


def test_agent_api_exposes_capabilities_and_requires_an_active_run():
 app,_=client_app()
 with TestClient(app) as c:
  assert c.get('/api/operations-tools/agent').json()['name']=='产业链运维智能体'
  assert c.post('/api/operations-tools/agent/run',json={'message':'巡检','use_llm':False}).status_code==409


def test_agent_api_inspection_draft_and_real_solver_keep_confirmation_boundaries():
 app,_=client_app()
 with TestClient(app) as c:
  c.post('/api/operations-tools/plans/activate',json={})
  before=c.get('/api/operations-tools/current').json()['instance']
  body={'run_id':before['run_id'],'constraint_version':before['constraint_version'],'use_llm':False}
  inspected=c.post('/api/operations-tools/agent/run',json={**body,'message':'巡检当前计划'})
  assert inspected.status_code==200 and inspected.json()['status']=='analyzed'
  drafted=c.post('/api/operations-tools/agent/run',json={**body,'message':'M1故障20分钟，请生成方案'})
  assert drafted.status_code==200 and drafted.json()['prepared_event']['draft']
  assert 'adjustment_id' not in drafted.json()
  incomplete=c.post('/api/operations-tools/agent/run',json={**body,'message':'一台机器故障，生成方案'})
  assert incomplete.status_code==200 and 'adjustment_id' not in incomplete.json()
  no_changes=c.post('/api/operations-tools/agent/run',json={**body,'message':'生成调整方案'})
  assert no_changes.status_code==200 and no_changes.json()['status']=='no_changes'
  assert 'adjustment_id' not in no_changes.json()
  confirmed=c.post('/api/operations-tools/events',json={'run_id':before['run_id'],'type':'resource_unavailable','target_id':'M1','data':{'expected_recovery_at':NOW+1200}})
  assert confirmed.status_code==200,confirmed.text
  body['constraint_version']=c.get('/api/operations-tools/current').json()['instance']['constraint_version']
  generated=c.post('/api/operations-tools/agent/run',json={**body,'message':'生成调整方案'})
  assert generated.status_code==200,generated.text
  assert generated.json()['status']=='solving'
  job=wait_job(c,generated.json()['adjustment_id'])
  assert job['status']=='done' and job['result']['candidates'][0]['validation']['passed']
  after=c.get('/api/operations-tools/current').json()['instance']
  assert after['event_seq']==1 and after['plan_revision']==before['plan_revision']
  assert not next(r for r in after['resources'] if r['id']=='M1')['available']
  old=c.post('/api/operations-tools/agent/run',json={**body,'run_id':'wrong','message':'巡检'})
  assert old.status_code==409


def test_state_change_while_agent_is_analyzing_rejects_its_old_solver_request(monkeypatch):
 from metaforge.operations import assistant
 original=assistant.assist;entered=threading.Event();release=threading.Event()
 def slow(*args,**kwargs):
  entered.set();assert release.wait(5)
  return original(*args,**kwargs)
 monkeypatch.setattr(assistant,'assist',slow)
 app,_=client_app()
 with TestClient(app) as c,ThreadPoolExecutor(max_workers=1) as pool:
  c.post('/api/operations-tools/plans/activate',json={})
  before=c.get('/api/operations-tools/current').json()['instance']
  future=pool.submit(c.post,'/api/operations-tools/agent/run',json={'run_id':before['run_id'],'constraint_version':before['constraint_version'],'message':'生成调整方案','use_llm':False})
  try:
   assert entered.wait(3)
   changed=c.post('/api/operations-tools/events',json={'run_id':before['run_id'],'type':'resource_unavailable','target_id':'M1','data':{}})
   assert changed.status_code==200
  finally:release.set()
  result=future.result(timeout=5)
  assert result.status_code==409 and '变化' in result.json()['detail']


def test_agent_keeps_unbound_stages_explicit_and_does_not_hide_failed_tools(monkeypatch):
 from metaforge.operations import assistant
 from metaforge.tools.base import ToolResult
 s=state();s['plan']['coverage']={'production':'bound','assembly':'unbound','delivery':'unbound'}
 result=assist(s,'巡检当前计划',NOW,False)
 assert '组装' in result['summary'] and '尚未绑定' in result['summary']
 assert len([i for i in result['issues'] if i['kind']=='coverage'])==2
 original=assistant.run_tool
 def broken(name,params,ctx):
  if name=='operations.query_state':return ToolResult(ok=False,error='fixture read failed')
  return original(name,params,ctx)
 monkeypatch.setattr(assistant,'run_tool',broken)
 failure=assist(s,'生成调整方案',NOW,False)
 assert failure['status']=='failed' and failure['plan_request'] is None
 assert '核验失败' in failure['summary'] and not failure['llm_used']


def configured_model(monkeypatch, responder):
 from metaforge.orchestrator import llm_config
 from metaforge.orchestrator.llm.client import LlmClient
 monkeypatch.setattr(llm_config,'llm_enabled',lambda:True)
 monkeypatch.setattr(LlmClient,'from_env',classmethod(lambda cls:LlmClient('fixture-secret','fixture-model',60)))
 monkeypatch.setattr(LlmClient,'invoke_json',responder)


def test_plain_questions_and_inspection_reach_model_with_current_tool_facts(monkeypatch):
 import json
 calls=[]
 def respond(client,**kwargs):
  calls.append(json.loads(kwargs['user']))
  assert client.timeout_sec==30
  return {'summary':'这是针对本次问题的模型回答。'}
 configured_model(monkeypatch,respond)
 s=state();before=copy.deepcopy(s)
 for question in ['为什么目前有任务受阻？','你能帮助我做什么？','巡检当前计划']:
  result=assist(s,question,NOW)
  assert result['llm_used'] and result['llm_status']=='used'
  assert result['summary']=='这是针对本次问题的模型回答。'
  assert result['llm_model']=='fixture-model' and result['llm_error'] is None
  assert result['trace'][-1]['tool']=='llm.answer' and result['trace'][-1]['ok']
  assert calls[-1]['question']==question
  assert calls[-1]['facts']['run_id']==s['run_id']
  from datetime import datetime, timedelta, timezone
  assert calls[-1]['facts']['clock_at']==datetime.fromtimestamp(NOW,timezone(timedelta(hours=8))).isoformat(timespec='seconds')
  assert calls[-1]['facts']['timezone']=='Asia/Shanghai'
 assert s==before


def test_model_outage_reports_reason_and_preserves_real_tool_results(monkeypatch):
 from requests.exceptions import ConnectionError, Timeout
 for error,expected in [(ConnectionError('fixture-secret'), '连接失败'),(Timeout('fixture-secret'),'超时')]:
  def fail(client,**kwargs):raise error
  configured_model(monkeypatch,fail)
  result=assist(state(),'当前怎样？',NOW)
  assert not result['llm_used'] and result['llm_status']=='failed'
  assert expected in result['llm_message']
  assert 'fixture-secret' not in str(result)
  assert '任务执行中' in result['summary'] and result['facts']['run_id']
  assert result['status']=='analyzed' and result['trace'][-1]['ok'] is False


def test_unconfigured_model_and_explicit_tool_only_mode_are_distinguished(monkeypatch):
 from metaforge.orchestrator import llm_config
 monkeypatch.setattr(llm_config,'llm_enabled',lambda:False)
 result=assist(state(),'现在是什么状态？',NOW)
 assert result['llm_status']=='disabled' and '未启用' in result['llm_message']
 readonly=assist(state(),'现在是什么状态？',NOW,False)
 assert readonly['llm_status']=='skipped' and not readonly['llm_used']


def test_model_cannot_create_event_or_solver_command_through_answer_fields(monkeypatch):
 configured_model(monkeypatch,lambda client,**kwargs:{'summary':'没有待处理变化，请先登记。',
  'plan_request':{'start':True},'prepared_event':{'draft':{'type':'resource_unavailable'}}})
 s=state();before=copy.deepcopy(s)
 result=assist(s,'生成调整方案',NOW)
 assert result['llm_used'] and result['status']=='no_changes'
 assert result['plan_request'] is None and result['prepared_event']['draft'] is None
 assert s==before


def test_invalid_model_response_and_http_failure_have_visible_safe_feedback(monkeypatch):
 from metaforge.orchestrator.llm.client import LlmClientError
 configured_model(monkeypatch,lambda client,**kwargs:{'unrelated':'fixture'})
 result=assist(state(),'你好',NOW)
 assert result['llm_status']=='failed' and not result['llm_used']
 assert '有效回答' in result['llm_message']
 def unauthorized(client,**kwargs):raise LlmClientError('http 401: fixture-secret')
 configured_model(monkeypatch,unauthorized)
 result=assist(state(),'你好',NOW)
 assert 'HTTP 401' in result['llm_message'] and 'fixture-secret' not in str(result)


def test_model_context_distinguishes_expired_recovery_from_actual_recovery(monkeypatch):
 import json
 captured=[]
 def respond(client,**kwargs):
  captured.append(json.loads(kwargs['user']))
  return {'summary':'预计时间已过仍需确认恢复，不能视为自动复机。'}
 configured_model(monkeypatch,respond)
 s=state();s['resources']['M1'].update(available=False,expected_recovery_at=NOW-1)
 s['forecast']={'status':'unresolved','message':'缺少有效恢复估计','schedule':[{'task_id':'O-A-T1','start_at':NOW,'end_at':NOW+1}]}
 result=assist(s,'M1为什么没有自动恢复？',NOW)
 facts=captured[0]['facts']
 assert facts['unavailable_details'][0]['recovery_overdue']
 assert facts['forecast_message']=='缺少有效恢复估计'
 assert all(stage['predicted_end_at'] is None for stage in facts['stages'])
 assert result['llm_used'] and s['resources']['M1']['available'] is False


def test_model_context_uses_explicit_beijing_dates_and_keeps_durations_numeric():
 from metaforge.operations.assistant import model_context
 raw={'clock_at':1794924904,'expected_recovery_at':1794924904,
      'nested':{'actual_start_at':None,'work_seconds':120,'quantity':5,'available':True},
      'slots':[{'end_at':1794924904,'duration_seconds':3600}]}
 local=model_context(raw)
 assert local['clock_at']=='2026-11-17T22:15:04+08:00'
 assert local['expected_recovery_at']=='2026-11-17T22:15:04+08:00'
 assert local['nested']==raw['nested']
 assert local['slots'][0]['duration_seconds']==3600
 assert raw['clock_at']==1794924904
