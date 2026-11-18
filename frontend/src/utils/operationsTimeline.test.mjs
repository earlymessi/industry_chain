import test from 'node:test'
import assert from 'node:assert/strict'
import { timelineAxis, timelineRows } from './operationsTimeline.js'
import { commitmentSummary, chainHandoffs, planWindow } from './operationsPlan.js'
const DAY = 86400
const START = Date.parse('2026-11-16T16:00:00Z') / 1000
function fixture() {
  const tasks = [{id:'P',kind:'production',name:'生产',status:'pending'},{id:'A',kind:'assembly',name:'组装',status:'pending'},{id:'D',kind:'delivery',name:'配送',status:'pending'}]
  const schedule = [{task_id:'P',resource_id:'M',start_at:START+3600,end_at:START+7200},{task_id:'A',resource_id:'S',start_at:START+7300,end_at:START+7360},{task_id:'D',resource_id:'V',start_at:START+8*DAY+60,end_at:START+8*DAY+180}]
  return {tasks,schedule,forecast:{status:'available',schedule},resources:[{id:'M',kind:'production',name:'机台'},{id:'S',kind:'assembly',name:'工位'},{id:'V',kind:'vehicle',name:'车辆'}],plan:{supplies:[{id:'SUP',name:'采购备货',role:'supplier_ready',available_at:START+8000}]},received_supplies:[]}
}

test('7天刻度按北京时间的日期，4周保留逐日网格与周刻度',()=>{
  const week=timelineAxis(planWindow(START,168)),month=timelineAxis(planWindow(START,672))
  assert.equal(week.dateAxis,true);assert.equal(week.ticks.length,8)
  assert.equal(week.ticks[1]-week.ticks[0],DAY)
  assert.equal(month.ticks.length,5);assert.equal(month.ticks[1]-month.ticks[0],7*DAY)
  assert.equal(month.minorTicks.length,29)
  assert.ok(month.width>week.width)
  assert.equal(timelineAxis(planWindow(START,4)).dateAxis,false)
})
test('四种观察窗口只筛选，不改变工序和配送的原始秒级时间',()=>{
  const st=fixture()
  for(const hours of [4,24,168,672]){
    const rows=timelineRows(st,planWindow(START,hours),'all',START)
    const p=rows.find(r=>r.id==='M').bars[0]
    assert.equal(p.start,START+3600);assert.equal(p.end,START+7200)
    const a=rows.find(r=>r.id==='S').bars[0]
    assert.equal(a.end-a.start,60)
    const d=rows.find(r=>r.id==='V').bars
    assert.equal(d.length,hours===672?1:0)
    if(d.length){assert.equal(d[0].start,START+8*DAY+60);assert.equal(d[0].end-d[0].start,120)}
  }
})
test('跨周任务保留完整时间，4周不人为扩展成按周占用',()=>{
  const st=fixture();st.schedule[0].start_at=START+7*DAY-60;st.schedule[0].end_at=START+7*DAY+60
  for(const hours of [168,672]){
    const p=timelineRows(st,planWindow(START,hours),'production',START)[0].bars[0]
    assert.equal(p.end-p.start,120)
  }
})
test('实际执行段与失效预测分开，不把原安排显示为已重新计算',()=>{
  const st=fixture();st.forecast={status:'unresolved',schedule:[]}
  st.tasks[0].status='completed';st.tasks[0].resource_id='M';st.tasks[0].actual_start_at=START+3601;st.tasks[0].actual_end_at=START+7199
  const rows=timelineRows(st,planWindow(START,24),'all',START+7200)
  const p=rows.find(r=>r.id==='M').bars
  assert.equal(p.length,1);assert.equal(p[0].actual,true);assert.equal(p[0].start,START+3601)
  assert.match(rows.find(r=>r.id==='S').bars[0].label,/原安排/)
})
test('物料里程碑和车辆均归正确环节，已收到标记不伪造实际到货时间',()=>{
  const st=fixture();st.received_supplies=['SUP']
  const material=timelineRows(st,planWindow(START,24),'material',START)
  assert.equal(material.length,1);assert.equal(material[0].supplies[0].received,true)
  assert.equal(material[0].supplies[0].available_at,START+8000)
  assert.deepEqual(timelineRows(st,planWindow(START,672),'delivery',START).map(r=>r.id),['V'])
})
test('未设承诺交期仍能显示预计完成，但不冒充已知零延期',()=>{
  const m={orders:[{due_at:null,completion_at:START+60,delay_seconds:null},{due_at:null,completion_at:START+180,delay_seconds:null}],total_delay_seconds:0}
  assert.deepEqual(commitmentSummary(m),{unknownDue:2,unknownCompletion:0,completionAt:START+180,delaySeconds:0})
  m.orders[1].completion_at=null
  assert.equal(commitmentSummary(m).completionAt,null);assert.equal(commitmentSummary(m).unknownCompletion,1)
})
test('已设交期的延期指标和未设交期计数分别保留',()=>{
  const m={orders:[{due_at:START,completion_at:START+60,delay_seconds:60},{due_at:null,completion_at:START+100}],total_delay_seconds:60}
  assert.equal(commitmentSummary(m).unknownDue,1);assert.equal(commitmentSummary(m).delaySeconds,60)
  assert.equal(commitmentSummary({}).completionAt,null)
})
test('交接预览读取同一计划秒级安排，只以已选部件判定生产完成',()=>{
  const p={tasks:[{id:'P',kind:'production'},{id:'UNUSED',kind:'production'},{id:'A',kind:'assembly'},{id:'L',kind:'loading'},{id:'D',kind:'delivery'}],schedule:[{task_id:'P',end_at:START+30},{task_id:'UNUSED',end_at:START+9999},{task_id:'A',end_at:START+90},{task_id:'L',start_at:START+100,end_at:START+160},{task_id:'D',end_at:START+300}],orders:[{id:'PART',completion_task_ids:['P']}],chain_config:{parts:[{order_id:'PART',enabled:true}]},time_mapping:[{module:'logistics',departure_at:START+180}]}
  assert.deepEqual(chainHandoffs(p).map(x=>x.at),[30,90,100,180,300].map(x=>START+x))
  p.schedule=p.schedule.filter(s=>s.task_id!=='D');p.time_mapping=[]
  assert.equal(chainHandoffs(p)[4].at,null);assert.equal(chainHandoffs(p)[3].at,null)
})
