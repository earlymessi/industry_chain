<template>
  <div class="ops-timeline" v-if="resources.length">
    <svg :viewBox="`0 0 1120 ${height}`" role="img" aria-label="生产、组装与配送统一时间轴">
      <g v-for="(tick, i) in ticks" :key="tick">
        <line :x1="x(tick)" y1="28" :x2="x(tick)" :y2="height - 15" stroke="#e7edf4" stroke-dasharray="3 4" />
        <text :x="x(tick)" y="18" text-anchor="middle" class="tick">{{ time(tick) }}</text>
      </g>
      <g v-for="(r, index) in resources" :key="r.id">
        <text x="12" :y="54 + index * 38" class="resource">{{ r.name }}</text>
        <line x1="155" :y1="68 + index * 38" x2="1100" :y2="68 + index * 38" stroke="#f0f3f8" />
        <g v-for="bar in bars(r.id)" :key="bar.key" @click="$emit('select', bar.task)" class="bar">
          <rect :x="x(bar.start)" :y="36 + index * 38" :width="Math.max(3, x(bar.end) - x(bar.start))" height="25" rx="5" :fill="bar.color" :opacity="bar.opacity" />
          <text v-if="x(bar.end) - x(bar.start) > 38" :x="x(bar.start) + 6" :y="53 + index * 38" class="bar-label">{{ bar.label }}</text>
          <title>{{ bar.task.name }} · {{ time(bar.start) }}—{{ time(bar.end) }} · {{ bar.actual ? '已发生执行段' : '预计安排' }}</title>
        </g>
      </g>
      <g v-if="now >= begin && now <= end">
        <line :x1="x(now)" y1="26" :x2="x(now)" :y2="height - 12" stroke="#ef6868" stroke-width="2" />
        <circle :cx="x(now)" cy="29" r="4" fill="#ef6868" />
        <text :x="Math.min(1045, x(now) + 6)" :y="height - 2" fill="#d44d55" font-size="11">当前 {{ time(now) }}</text>
      </g>
    </svg>
  </div>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ instance: { type: Object, required: true }, now: Number, window: Object, stage: { type: String, default: 'all' } })
import { inStage } from '../../utils/operationsPlan'
defineEmits(['select'])
const colors = { production: '#4e80e8', assembly: '#2aa899', loading: '#b18bdb', delivery: '#e4a54b', return: '#9aa9bf' }
const resources = computed(() => props.instance.resources.filter((r) => inStage(r.kind === 'vehicle' ? 'delivery' : r.kind, props.stage)))
const height = computed(() => 55 + resources.value.length * 38)
const begin = computed(() => props.window?.begin ?? props.now - 15 * 60)
const end = computed(() => props.window?.end ?? props.now + 4 * 3600)
const ticks = computed(() => Array.from({ length: 7 }, (_, i) => begin.value + i * (end.value - begin.value) / 6))
const x = (t) => 155 + Math.max(0, Math.min(1, (t - begin.value) / (end.value - begin.value))) * 945
const time = (t) => new Date(t * 1000).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit' })
function bars(resourceId) {
  const taskMap = Object.fromEntries(props.instance.tasks.map((t) => [t.id, t]))
  const result = []
  const forecast = props.instance.forecast?.status === 'available' ? props.instance.forecast.schedule : props.instance.schedule
  for (const slot of forecast) {
    const t = taskMap[slot.task_id]
    if (t && slot.resource_id === resourceId && t.status !== 'completed' && slot.end_at >= begin.value && slot.start_at <= end.value) result.push({ key: t.id + '-p', start: slot.start_at, end: slot.end_at, label: t.order_id || t.id, task: t, color: colors[t.kind], opacity: 0.4, actual: false })
  }
  for (const t of props.instance.tasks) for (const [i, seg] of (t.segments || []).entries()) {
    if (seg.resource_id === resourceId && (seg.end_at ?? props.now) >= begin.value && seg.start_at <= end.value) result.push({ key: t.id + i, start: seg.start_at, end: seg.end_at ?? props.now, label: t.order_id || t.id, task: t, color: colors[t.kind], opacity: 1, actual: true })
  }
  return result
}
</script>

<style scoped>
.ops-timeline { width: 100%; overflow: auto; }
svg { min-width: 760px; width: 100%; display: block; }
.tick { font: 11px sans-serif; fill: #8493a8; }
.resource { font: 12px sans-serif; fill: #43546b; }
.bar { cursor: pointer; }
.bar:hover { filter: brightness(.92); }
.bar-label { fill: white; font: 10px sans-serif; pointer-events: none; }
</style>
