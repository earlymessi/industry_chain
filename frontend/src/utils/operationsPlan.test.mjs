import test from 'node:test'
import assert from 'node:assert/strict'
import { aggregatePlan, planRows, planWindow, visiblePlanRows } from './operationsPlan.js'

const DAY = 86400
const START = Date.parse('2026-11-09T16:00:00Z') / 1000 // 北京 11月10日零点
function fixture() {
  const tasks = [{ id: 'P', name: '跨日生产', kind: 'production', status: 'pending' },
    { id: 'A', name: '组装', kind: 'assembly', status: 'pending' },
    { id: 'D', name: '配送', kind: 'delivery', status: 'pending' }]
  const schedule = [{ task_id: 'P', resource_id: 'M1', start_at: START + 23 * 3600, end_at: START + 25 * 3600 },
    { task_id: 'A', resource_id: 'S1', start_at: START + 26 * 3600, end_at: START + 27 * 3600 },
    { task_id: 'D', resource_id: 'V1', start_at: START + 28 * 3600, end_at: START + 29 * 3600 }]
  return { tasks, schedule, forecast: { status: 'available', schedule }, resources: [
    { id: 'M1', kind: 'production', working_windows: [[START, START + 2 * DAY]] },
    { id: 'S1', kind: 'assembly', working_windows: [[START, START + 2 * DAY]] },
    { id: 'V1', kind: 'vehicle', working_windows: [[START, START + 2 * DAY]] }],
  plan: { orders: [{ id: 'O', due_at: START + 30 * 3600 }], supplies: [{ id: 'SUP', available_at: START + DAY }] } }
}

test('今日按北京时间零点划分，实时窗口保留过去15分钟', () => {
  const now = START + 8 * 3600
  assert.deepEqual(planWindow(now, 24), { begin: START, end: START + DAY })
  assert.deepEqual(planWindow(now, 4), { begin: now - 900, end: now + 4 * 3600 })
})

test('7天按天汇总，跨日任务的占用拆分且不重复累计', () => {
  const buckets = aggregatePlan(fixture(), planWindow(START, 168), 168)
  assert.equal(buckets.length, 7)
  assert.equal(buckets[0].loadHours, 1)
  assert.equal(buckets[1].loadHours, 3)
  assert.equal(buckets.reduce((n, b) => n + b.loadHours, 0), 4)
  assert.equal(buckets[0].supplyCount, 0)
  assert.equal(buckets[1].supplyCount, 1) // 边界到货只归入新一天
  assert.equal(buckets[2].hasPlan, false)
  assert.equal(buckets[2].calendarHours, null)
})

test('四周按周汇总，不把缺失日历或未给需求显示成充足产能', () => {
  const buckets = aggregatePlan(fixture(), planWindow(START, 672), 672)
  assert.equal(buckets.length, 4)
  assert.equal(buckets[0].loadHours, 4)
  assert.equal(buckets[0].calendarHours, null)
  assert.equal(buckets[1].hasPlan, false)
  assert.equal(buckets[1].dueCount, 0)
})

test('环节筛选作用于计划与资源，车辆归配送', () => {
  const st = fixture()
  const b = aggregatePlan(st, planWindow(START, 168), 168, 'delivery')
  assert.equal(b[1].delivery, 1)
  assert.equal(b[1].production, 0)
  assert.equal(b[1].loadHours, 1)
  assert.equal(b[1].calendarHours, 24)
  const materials = aggregatePlan(st, planWindow(START, 168), 168, 'material')
  assert.equal(materials[0].hasPlan, false)
  assert.equal(materials[1].hasPlan, true)
})

test('完成任务使用实际起止；预测失效不把原安排伪装成新预测', () => {
  const st = fixture()
  Object.assign(st.tasks[0], { status: 'completed', actual_start_at: START + 1, actual_end_at: START + 1801 })
  assert.equal(planRows(st).find(t => t.id === 'P').end_at, START + 1801)
  st.forecast = { status: 'unresolved', schedule: [] }
  const b = aggregatePlan(st, planWindow(START, 168), 168)
  assert.equal(b[1].loadHours, null)
})

test('实时运维仍能看到超过原计划时刻的中断/阻塞任务', () => {
  const st = fixture(), now = START + 3 * DAY
  st.forecast = { status: 'unresolved', schedule: [] }
  Object.assign(st.tasks[0], { status: 'paused', blocked_reason: '设备故障' })
  Object.assign(st.tasks[1], { blocked_reason: '缺少物料' })
  assert.deepEqual(visiblePlanRows(st, planWindow(now, 4), 'all', now).map(t => t.id), ['P', 'A'])
  assert.equal(visiblePlanRows(st, planWindow(now, 24)).length, 0)
})
