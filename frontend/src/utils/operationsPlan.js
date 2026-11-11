const DAY = 86400
export const inStage = (kind, stage) => !stage || stage === 'all' || (stage === 'delivery' ? ['loading', 'delivery', 'return'].includes(kind) : kind === stage)
export const beijingDay = (now) => Math.floor((now + 8 * 3600) / DAY) * DAY - 8 * 3600

export function planWindow(now, hours) {
  const begin = hours === 4 ? now - 900 : beijingDay(now)
  return { begin, end: hours === 4 ? now + 14400 : begin + hours * 3600 }
}

export function planRows(instance) {
  if (!instance) return []
  const published = Object.fromEntries(instance.schedule.map((s) => [s.task_id, s]))
  const forecast = instance.forecast?.status === 'available' ? instance.forecast.schedule : instance.schedule
  const projected = Object.fromEntries(forecast.map((s) => [s.task_id, s]))
  return instance.tasks.map((t) => {
    const row = projected[t.id] || published[t.id] || {}
    return { ...t, ...row, id: t.id, start_at: t.actual_start_at ?? row.start_at, end_at: t.actual_end_at ?? row.end_at,
      resource_id: t.resource_id || row.resource_id, forecastKnown: t.status === 'completed' || instance.forecast?.status === 'available' }
  }).sort((a, b) => (a.start_at ?? Infinity) - (b.start_at ?? Infinity))
}

export function visiblePlanRows(instance, window, stage = 'all', liveNow = null) {
  return planRows(instance).filter((t) => inStage(t.kind, stage) && (
    (t.start_at < window.end && t.end_at > window.begin) ||
    (liveNow != null && t.status !== 'completed' && (['running', 'paused'].includes(t.status) || (t.blocked_reason && (t.end_at == null || t.end_at < liveNow))))
  ))
}

export function aggregatePlan(instance, window, hours, stage = 'all') {
  if (!instance) return []
  const rows = planRows(instance).filter((t) => inStage(t.kind, stage))
  const size = hours === 672 ? 7 * DAY : DAY
  const resources = instance.resources.filter((r) => stage === 'material' ? false : inStage(r.kind === 'vehicle' ? 'delivery' : r.kind, stage))
  const overlap = (a, b, start, end) => Math.max(0, Math.min(b, end) - Math.max(a, start))
  const result = []
  for (let start = window.begin; start < window.end; start += size) {
    const end = Math.min(start + size, window.end)
    const tasks = rows.filter((t) => t.start_at < end && t.end_at > start)
    const supplies = instance.plan.supplies.filter((s) => s.available_at >= start && s.available_at < end)
    const due = instance.plan.orders.filter((o) => o.due_at != null && o.role !== 'component' && o.due_at >= start && o.due_at < end)
    const calendarKnown = resources.length > 0 && resources.every((r) => Math.max(...r.working_windows.map((w) => w[1])) >= end)
    result.push({ start, end, production: tasks.filter((t) => t.kind === 'production').length,
      assembly: tasks.filter((t) => t.kind === 'assembly').length, delivery: tasks.filter((t) => t.kind === 'delivery').length,
      supplyCount: supplies.length, dueCount: due.length, taskCount: tasks.length,
      hasPlan: stage === 'material' ? supplies.length > 0 : tasks.length > 0 || due.length > 0,
      loadHours: tasks.every((t) => t.forecastKnown) ? tasks.reduce((sum, t) => sum + overlap(t.start_at, t.end_at, start, end), 0) / 3600 : null,
      calendarHours: calendarKnown ? resources.reduce((sum, r) => sum + r.working_windows.reduce((n, w) => n + overlap(w[0], w[1], start, end), 0), 0) / 3600 : null })
  }
  return result
}
