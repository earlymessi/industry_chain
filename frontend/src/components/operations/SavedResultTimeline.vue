<template>
  <div class="result-timeline">
    <div class="controls">
      <el-radio-group v-model="grain" size="small"><el-radio-button v-for="g in grains" :key="g.minutes" :value="g.minutes">{{g.label}}</el-radio-button></el-radio-group>
      <el-button size="small" @click="focusFirst">定位任务</el-button>
      <small>北京时间 · 预览映射 · 拖动查看，双击回到当前</small>
    </div>
    <div class="range">{{label(windowStart)}} — {{label(windowEnd)}}<span>当前 {{label((now-origin)/60)}}</span></div>
    <div ref="timelineElement" class="scroll" :class="{'is-dragging':pan.state.dragging}" tabindex="0" aria-label="拖动或使用左右方向键移动历史计划时间轴" @pointerdown="pan.start" @pointermove="pan.move" @pointerup="pan.end" @pointercancel="pan.end" @lostpointercapture="pan.end" @click.capture="pan.suppressClick" @dblclick="resume" @wheel="pan.wheel" @keydown.left.prevent="pan.step(-1)" @keydown.right.prevent="pan.step(1)">
      <svg :viewBox="`0 0 ${width} ${height}`" role="img" aria-label="北京时间历史计划甘特图" style="width:100%;display:block">
        <g v-for="(tick,i) in ticks" :key="i"><line :x1="x(tick)" y1="30" :x2="x(tick)" :y2="height-12" stroke="#e8edf3" /><text :x="x(tick)" y="19" :text-anchor="i===0 ? 'start' : i===ticks.length-1 ? 'end' : 'middle'" font-size="11" fill="#7c8a9b">{{tickLabel(tick)}}</text></g>
        <g v-for="(resource,index) in resources" :key="resource"><text x="8" :y="53+index*32" font-size="11" fill="#52647c">{{resource.length>17 ? resource.slice(0,17)+'…' : resource}}<title>{{resource}}</title></text><line x1="190" :y1="66+index*32" :x2="width-20" :y2="66+index*32" stroke="#f1f4f7" /></g>
        <rect v-for="(task,index) in visible" :key="task.id || index" :x="x(Math.max(task.start,windowStart))" :y="36+resources.indexOf(task.resource)*32" :width="Math.max(2,x(Math.min(task.end,windowEnd))-x(Math.max(task.start,windowStart)))" height="22" rx="3" :fill="colors[index%colors.length]"><title>{{task.name}} · {{label(task.start)}}—{{label(task.end)}} · {{Number((task.end-task.start).toFixed(1))}}分钟</title></rect>
        <g v-if="now >= viewWindow.begin && now <= viewWindow.end"><line :x1="x((now-origin)/60)" y1="28" :x2="x((now-origin)/60)" :y2="height-12" stroke="#ef6868" stroke-width="2"><title>当前 {{label((now-origin)/60)}}</title></line><text :x="x((now-origin)/60)+5" y="29" font-size="10" fill="#df5656">当前</text></g>
        <text v-if="!visible.length" :x="Math.max(210,width/2)" y="65" font-size="12" fill="#8a98aa">此时间段暂无任务，可拖动或定位任务</text>
      </svg>
    </div>
  </div>
</template>
<script setup>
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {liveTimelineWindow} from '../../utils/timelineNavigation'
import {useTimelinePan} from '../../composables/useTimelinePan'
const props=defineProps({rows:{type:Array,default:()=>[]},originAt:{type:Number,default:null},currentTime:{type:Number,default:null}})
const wallNow=ref(Date.now()/1000),previewOrigin=ref(props.originAt ?? wallNow.value)
const origin=computed(()=>props.originAt ?? previewOrigin.value)
const now=computed(()=>props.currentTime ?? wallNow.value)
const grain=ref(240),following=ref(true),manualWindow=ref(null)
const colors=['#547bca','#3fa7a0','#c68b51','#8771bb','#588eaf']
const grains=[{minutes:240,label:'小时 · 4h'},{minutes:1440,label:'天 · 24h'},{minutes:10080,label:'周 · 7天'},{minutes:40320,label:'4周'},{minutes:0,label:'全计划'}]
const total=computed(()=>Math.max(60,...props.rows.map(r=>Number(r.end))))
const viewWindow=computed(()=>manualWindow.value || liveTimelineWindow(now.value,(grain.value || 240)/60))
const windowStart=computed(()=>(viewWindow.value.begin-origin.value)/60),windowEnd=computed(()=>(viewWindow.value.end-origin.value)/60)
const resources=computed(()=>[...new Set(props.rows.map(r=>r.resource || r.resource_id || '资源'))])
const visible=computed(()=>props.rows.filter(r=>r.start<windowEnd.value && r.end>windowStart.value))
const height=computed(()=>Math.max(100,resources.value.length*32+48))
const ticks=computed(()=>Array.from({length:7},(_,i)=>windowStart.value+(windowEnd.value-windowStart.value)*i/6))
const pan=useTimelinePan(()=>viewWindow.value,navigate,190,20),timelineElement=pan.element
const width=computed(()=>pan.state.width)
function navigate(window){following.value=false;manualWindow.value={...window}}
function resume(){following.value=true;manualWindow.value=null;if(!grain.value)grain.value=240}
function showAll(){const begin=Math.min(now.value,origin.value+Math.min(0,...props.rows.map(r=>Number(r.start)))*60),end=Math.max(now.value+60,origin.value+total.value*60),padding=Math.max(60,(end-begin)*.03);navigate({begin:begin-padding,end:end+padding})}
function focusFirst(){const minute=Math.min(...props.rows.map(r=>Number(r.start)));if(Number.isFinite(minute))navigate(liveTimelineWindow(origin.value+minute*60,(grain.value || 240)/60))}
const x=minute=>190+(minute-windowStart.value)/Math.max(1,windowEnd.value-windowStart.value)*(width.value-210)
const date=minute=>new Date((origin.value+minute*60)*1000)
const label=minute=>date(minute).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})
const tickLabel=minute=>date(minute).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',...(windowEnd.value-windowStart.value>=2*1440?{month:'2-digit',day:'2-digit'}:{hour:'2-digit',minute:'2-digit'}),hour12:false})
watch(grain,(value,old)=>{if(!value)showAll();else if(!old)resume();else if(!following.value){const range=viewWindow.value;navigate(liveTimelineWindow(range.begin+(range.end-range.begin)*.2,value/60))}})
watch(()=>props.originAt,()=>{pan.end();resume()})
let timer
onMounted(()=>{timer=setInterval(()=>{wallNow.value=Date.now()/1000},1000)})
onUnmounted(()=>clearInterval(timer))
</script>
<style scoped>
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:12px 0}.controls small{font-size:12px;color:#8795a6}.range{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;color:#7c8a9b;font-size:12px;margin:8px 0}.scroll{overflow:auto;border:1px solid #edf0f4;border-radius:5px;background:#fff;touch-action:pan-y;cursor:grab;user-select:none}.scroll.is-dragging{cursor:grabbing}
</style>
