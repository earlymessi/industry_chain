import { beijingDay, inStage } from './operationsPlan.js'
const DAY = 86400
const inside = (start, end, window) => Number.isFinite(start) && Number.isFinite(end) && start < window.end && end > window.begin

export function timelineAxis(window) {
  const span = window.end - window.begin
  let ticks
  if (span >= 6 * DAY) {
    const step = span > 8 * DAY ? 7 * DAY : DAY
    ticks = []
    for (let at = beijingDay(window.begin); at <= window.end; at += step) if (at >= window.begin) ticks.push(at)
  } else ticks = Array.from({ length: 7 }, (_, i) => window.begin + i * span / 6)
  return { ticks, minorTicks: span > 8 * DAY ? Array.from({ length: Math.ceil(span / DAY) + 1 }, (_, i) => window.begin + i * DAY) : [],
    dateAxis: span >= 6 * DAY, width: span > 8 * DAY ? 1720 : 1120 }
}

export function timelineRows(instance, window, stage = 'all', now) {
  if (!instance) return []
  const tasks = new Map(instance.tasks.map(t => [t.id, t]))
  const projected = instance.forecast?.status === 'available'
  const rows = instance.resources.filter(r => inStage(r.kind === 'vehicle' ? 'delivery' : r.kind, stage)).map(r => ({ ...r, bars: [], supplies: [] }))
  const byResource = new Map(rows.map(r => [r.id, r]))
  for (const slot of (projected ? instance.forecast.schedule : instance.schedule) || []) {
    const task = tasks.get(slot.task_id), row = byResource.get(slot.resource_id)
    if (row && task && task.status !== 'completed' && inside(slot.start_at, slot.end_at, window)) row.bars.push({ key: `${task.id}:plan`, start: slot.start_at, end: slot.end_at, task, actual: false, label: projected ? '预计安排' : '原安排（预测待更新）' })
  }
  for (const task of instance.tasks) {
    const segments = task.segments?.length ? task.segments : task.status === 'completed' && Number.isFinite(task.actual_start_at) && Number.isFinite(task.actual_end_at) ? [{ start_at: task.actual_start_at, end_at: task.actual_end_at, resource_id: task.resource_id }] : []
    for (const [i, segment] of segments.entries()) {
      const row = byResource.get(segment.resource_id), end = segment.end_at ?? now
      if (row && inside(segment.start_at, end, window)) row.bars.push({ key: `${task.id}:actual:${i}`, start: segment.start_at, end, task, actual: true, label: '已执行' })
    }
  }
  if (stage === 'material' || stage === 'all') {
    for (const supply of instance.plan.supplies || []) if (supply.available_at >= window.begin && supply.available_at < window.end) {
      const received = (instance.received_supplies || []).includes(supply.id)
      rows.push({ id: `supply:${supply.id}`, name: supply.name || supply.material_id, kind: 'material', bars: [], supplies: [{ ...supply, received }] })
    }
  }
  return rows
}
