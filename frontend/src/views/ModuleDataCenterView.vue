<template>
  <el-card shadow="never">
    <template #header><div class="header table-tools"><el-input v-model="keyword" placeholder="搜索计划名称" clearable style="width:220px" /><el-button :loading="loading" @click="refresh">刷新</el-button></div></template>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-table :data="filtered" v-loading="loading" stripe>
      <el-table-column prop="name" label="计划名称" min-width="140" />
      <el-table-column prop="algorithm" label="算法来源" min-width="185" />
      <el-table-column prop="units" label="数量" width="75" />
      <el-table-column prop="task_count" label="任务数" width="85" />
      <el-table-column label="计划跨度" width="110"><template #default="{row}">{{span(row)}}</template></el-table-column>
      <el-table-column label="保存时间" min-width="170"><template #default="{row}">{{new Date(row.created_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}}</template></el-table-column>
      <el-table-column label="状态" width="110"><template #default="{row}"><el-tag :type="row.test_case ? 'success' : row.compatible ? '' : 'warning'">{{row.test_case ? '完整基线' : row.result_kind==='metrics' ? '仅评估指标' : row.compatible ? '已保存' : '需工艺适配'}}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="245" fixed="right"><template #default="{row}"><el-button size="small" @click="inspect(row)">查看</el-button><el-button size="small" type="primary" @click="reuse(row)">复用结果</el-button><el-button size="small" plain @click="operations(row)">运维配置</el-button></template></el-table-column>
    </el-table>
  </el-card>
  <el-dialog v-model="opened" :title="detail?.name || '历史结果'" width="min(1150px,96vw)">
    <template v-if="detail"><div class="header"><span>{{detail.algorithm}} · {{detail.units}}台</span><el-select v-if="episodes>1" v-model="episode" size="small" style="width:150px"><el-option v-for="n in episodes" :key="n" :value="n" :label="`第${n}轮`" /></el-select><el-tag v-if="detail.test_case" type="success">全链路已校验</el-tag></div>
    <el-alert v-if="compatibility" :title="compatibility" type="warning" :closable="false" />
    <SavedResultTimeline v-if="timeline.length" :rows="timeline" :origin-at="previewOrigin" /><el-empty v-else description="此结果仅保存评估指标，无排程甘特" :image-size="60" /><p v-if="detail.payload.evaluation" class="hint">完成时间：{{detail.payload.evaluation.completion_time_mean ?? detail.payload.evaluation.makespans?.[0] ?? '—'}} · 平均奖励：{{detail.payload.evaluation.avg_reward ?? '—'}}</p>
    <el-table :data="timeline" size="small" max-height="270"><el-table-column prop="name" label="任务" min-width="180" /><el-table-column prop="resource" label="资源" min-width="140" /><el-table-column label="开始时间（北京时间）" min-width="150"><template #default="{row}">{{planTime(row.start)}}</template></el-table-column><el-table-column label="结束时间（北京时间）" min-width="150"><template #default="{row}">{{planTime(row.end)}}</template></el-table-column></el-table>
    <p class="hint">{{detail.payload.definition?.description || '保存时的计算结果快照，可重复查看和加载。'}}</p></template>
    <template #footer><el-button @click="opened=false">关闭</el-button><el-button v-if="detail" type="primary" @click="reuse(detail)">复用结果</el-button></template>
  </el-dialog>
</template>
<script setup>
import {computed,onMounted,ref,watch} from 'vue'
import {useRouter} from 'vue-router'
import {api} from '../api/client'
import SavedResultTimeline from '../components/operations/SavedResultTimeline.vue'
const props=defineProps({module:{type:String,required:true}}),router=useRouter()
const records=ref([]),keyword=ref(''),loading=ref(false),error=ref(''),opened=ref(false),detail=ref(null),episode=ref(1)
const previewOrigin=ref(Date.now()/1000)
const planTime=minute=>new Date((previewOrigin.value+Number(minute)*60)*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})
const filtered=computed(()=>records.value.filter(r=>r.name.toLowerCase().includes(keyword.value.toLowerCase())))
const episodes=computed(()=>detail.value?.payload.episodes?.length || 1)
const compatibility=computed(()=>detail.value?.payload.compatibility?.[episode.value-1] || '')
const timeline=computed(()=>{
 const p=detail.value?.payload;if(!p)return []
 if(p.timeline?.[0]?.start!=null)return p.timeline
 if(props.module==='assembly')return (p.episodes?.[episode.value-1] || []).map((r,i)=>({id:String(i),name:`产品${Number(r[3])+1} · 工序${r[4]??'源记录'}`,resource:`工位${r[2]}`,start:Number(r[0]),end:Number(r[0])+Number(r[1])}))
 return (p.timeline || []).map((r,i)=>({id:String(i),name:r.node_type==='customer'?`客户${r.cust_id}`:r.node_type,resource:`第${r.day}天 · 车辆${r.vehicle_id}`,start:(Number(r.day)-1)*1440+Number(r.arrive_min),end:(Number(r.day)-1)*1440+Math.max(Number(r.finish_min),Number(r.arrive_min)+.1)}))
})
const span=row=>row.span_minutes ? `${(row.span_minutes/1440).toFixed(1)}天` : row.episode_count ? `${row.episode_count}轮` : '完整结果'
async function refresh(){loading.value=true;error.value='';try{records.value=(await api.get(`/api/operations-tools/data-center/${props.module}`)).data.records}catch(e){error.value=String(e.response?.data?.detail||e.message)}finally{loading.value=false}}
async function inspect(row){try{detail.value=(await api.get(`/api/operations-tools/data-center/${props.module}/${row.id}`)).data;episode.value=detail.value.selected_episode || 1;previewOrigin.value=Date.now()/1000;opened.value=true}catch(e){error.value=String(e.response?.data?.detail||e.message)}}
function reuse(row){router.push({path:props.module==='assembly'?(row.task_count ? '/home/assembly/gantt':'/home/assembly/dashboard'):'/home/logistics-resource/results',query:{record:row.id}})}
function operations(row){router.push({path:'/home/operations-tools',query:{history_record:row.id,history_module:props.module}})}
onMounted(refresh);watch(()=>props.module,()=>{opened.value=false;refresh()})
</script>
<style scoped>.header{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.table-tools{justify-content:flex-end}.hint{font-size:12px;color:#8795a6}</style>
