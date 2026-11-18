<template>
  <div class="timeline-navigation"><small>拖动查看 · 双击空白回到当前</small></div>
  <div class="ops-timeline" :class="{'is-dragging':pan.state.dragging}">
    <div ref="timelineElement" class="timeline-canvas" tabindex="0" aria-label="拖动或使用左右方向键移动时间轴" @pointerdown="pan.start" @pointermove="pan.move" @pointerup="pan.end" @pointercancel="pan.end" @lostpointercapture="pan.end" @click.capture="pan.suppressClick" @dblclick="resumeOnDoubleClick" @wheel="pan.wheel" @keydown.left.prevent="pan.step(-1)" @keydown.right.prevent="pan.step(1)">
      <svg :viewBox="`0 0 ${axis.width} 30`" class="timeline-axis" role="group" aria-label="北京时间刻度">
        <rect :width="axis.width" height="30" fill="#fff" />
        <text x="12" y="19" class="axis-caption">北京时间</text>
        <g v-for="tick in axis.ticks" :key="tick"><text :x="x(tick)" y="19" :text-anchor="tick === window.end ? 'end' : tick === window.begin ? 'start' : 'middle'" class="tick">{{ tickLabel(tick) }}</text></g>
      </svg>
      <svg :viewBox="`0 0 ${axis.width} ${height}`" class="timeline-body" role="group" aria-label="产业链甘特图">
        <line v-for="tick in axis.minorTicks" :key="`day-${tick}`" :x1="x(tick)" y1="0" :x2="x(tick)" :y2="height" stroke="#f1f4f8" />
        <line v-for="tick in axis.ticks" :key="tick" :x1="x(tick)" y1="0" :x2="x(tick)" :y2="height" stroke="#e3eaf3" stroke-dasharray="3 4" />
        <g v-for="(row, index) in rows" :key="row.id">
          <text x="12" :y="index * 34 + 22" class="resource">{{ shortName(row.name) }}<title>{{ row.name }}</title></text>
          <line x1="155" :y1="(index + 1) * 34" :x2="axis.width - 20" :y2="(index + 1) * 34" stroke="#f0f3f8" />
          <g v-for="bar in row.bars" :key="bar.key" class="bar" role="button" tabindex="0" :aria-label="`${bar.task.name}，${bar.label}，${fullTime(bar.start)}至${fullTime(bar.end)}`" @click="$emit('select', bar.task)" @keydown.enter="$emit('select', bar.task)" @keydown.space.prevent="$emit('select', bar.task)">
            <rect :x="x(bar.start)" :y="index * 34 + 6" :width="Math.max(2, x(bar.end) - x(bar.start))" height="23" rx="4" :fill="colors[bar.task.kind] || '#8c9bb3'" :opacity="bar.actual ? 1 : .38" />
            <text v-if="x(bar.end) - x(bar.start) > 70" :x="x(bar.start) + 5" :y="index * 34 + 22" class="bar-label">{{ bar.task.name.slice(0, Math.max(2, Math.floor((x(bar.end) - x(bar.start) - 10) / 11))) }}</text>
            <title>{{ bar.task.name }} · {{ fullTime(bar.start) }}—{{ fullTime(bar.end) }} · {{ bar.label }}</title>
          </g>
          <g v-for="supply in row.supplies" :key="supply.id" :class="['supply-mark', { received: supply.received }]" role="button" :tabindex="supply.received ? -1 : 0" :aria-disabled="supply.received" :aria-label="supply.name" @click="!supply.received && $emit('supply', supply)" @keydown.enter="!supply.received && $emit('supply', supply)" @keydown.space.prevent="!supply.received && $emit('supply', supply)">
            <path :d="`M${x(supply.available_at)},9 l8,8 -8,8 -8,-8 Z`" :fill="supply.received ? '#2aa899' : '#9b78cc'" />
            <title>{{ supply.name }} · 计划{{ supply.role === 'supplier_ready' ? '备货' : '到货' }} {{ fullTime(supply.available_at) }} · {{ supply.received ? '已确认' : '待确认' }}</title>
          </g>
        </g>
        <line v-if="now >= window.begin && now <= window.end" :x1="x(now)" y1="0" :x2="x(now)" :y2="height" stroke="#ef6868" stroke-width="2"><title>当前 {{ fullTime(now) }}</title></line>
      </svg>
    </div>
  </div>

</template>
<script setup>
import { computed, watch } from 'vue'
import { useTimelinePan } from '../../composables/useTimelinePan'
import { timelineAxis, timelineRows } from '../../utils/operationsTimeline'
const props = defineProps({ instance: { type: Object, required: true }, now: Number, window: { type: Object, required: true }, stage: { type: String, default: 'all' } })
const emit = defineEmits(['select', 'supply', 'navigate', 'resume'])
const pan = useTimelinePan(() => props.window, window => emit('navigate', window))
const timelineElement = pan.element
function resumeOnDoubleClick(event) { if (!event.target.closest?.('.bar,.supply-mark')) emit('resume') }
watch(() => props.instance.run_id, () => pan.end())
const colors = { transport: '#9c7bd1', production: '#4e80e8', assembly: '#2aa899', loading: '#b18bdb', delivery: '#e4a54b', return: '#9aa9bf' }
const axis = computed(() => ({...timelineAxis(props.window), width:pan.state.width}))
const rows = computed(() => timelineRows(props.instance, props.window, props.stage, props.now))
const height = computed(() => Math.max(34, rows.value.length * 34))
const x = t => 155 + Math.max(0, Math.min(1, (t - props.window.begin) / (props.window.end - props.window.begin))) * (axis.value.width - 175)
const fullTime = t => new Date(t * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
const tickLabel = t => new Date(t * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', ...(axis.value.dateAxis ? { month: '2-digit', day: '2-digit' } : { hour: '2-digit', minute: '2-digit' }) })
const shortName = name => String(name).length > 12 ? `${String(name).slice(0, 11)}…` : name
</script>
<style scoped>
.timeline-navigation{display:flex;justify-content:flex-end;margin-bottom:8px;font-size:11px;color:#8a9aaf}.timeline-canvas{touch-action:pan-y;cursor:grab;user-select:none;outline-offset:-2px}.is-dragging .timeline-canvas,.is-dragging .bar,.is-dragging .supply-mark{cursor:grabbing}

.ops-timeline{width:100%;max-height:380px;overflow:auto;border:1px solid #edf1f6;border-radius:7px}.timeline-canvas{position:relative}svg{width:100%;display:block}.timeline-axis{position:sticky;top:0;z-index:1;background:#fff}.tick,.axis-caption{font:11px sans-serif;fill:#8493a8}.resource{font:12px sans-serif;fill:#43546b}.bar,.supply-mark{cursor:pointer}.bar:hover,.bar:focus{filter:brightness(.85);outline:none}.bar-label{fill:white;font:11px sans-serif;pointer-events:none}.supply-mark.received{cursor:default}.timeline-empty{text-align:center;padding:25px;font-size:12px;color:#8b9bb0}
</style>
