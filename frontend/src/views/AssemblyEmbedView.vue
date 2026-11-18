<template>
  <div class="embed-wrap">
    <div v-if="record" class="record-bar"><span>已加载：{{record.name}}</span><el-button size="small" @click="clearRecord">返回当前结果</el-button><el-button size="small" @click="router.push('/home/assembly/database')">数据中心</el-button></div>
    <iframe
      ref="frameRef"
      :key="generation"
      class="embed-frame"
      :src="iframeSrc"
      title="组装资源管控"
      @load="syncTab"
    />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {api} from '../api/client'
import {ElMessage} from 'element-plus'

const route = useRoute(), router=useRouter()
const frameRef = ref(null), record = ref(null), generation=ref(0)
let revision=0
async function loadRecord(key) {
  const turn=++revision
  if(!key){if(record.value)generation.value++;record.value=null;return}
  try{const {data}=await api.get(`/api/operations-tools/data-center/assembly/${encodeURIComponent(key)}`);if(turn!==revision)return;record.value=data;syncTab()}
  catch(e){if(turn===revision)ElMessage.error(String(e.response?.data?.detail||'历史结果加载失败'))}
}
function clearRecord(){const query={...route.query};delete query.record;router.replace({path:route.path,query})}
watch(()=>route.query.record,key=>loadRecord(key),{immediate:true})

const validTabs = ['dashboard', 'materials', 'gantt', 'charts', 'dynamic']

const tab = computed(() => {
  const value = String(route.params.tab || 'dashboard')
  return validTabs.includes(value) ? value : 'dashboard'
})

// 固定 src，避免切换侧栏时 iframe 重载导致评估结果丢失
const iframeSrc = '/masa-qmix/?embed=1'

function syncTab() {
  const target = frameRef.value?.contentWindow
  if (record.value) target?.postMessage({type:'masa-qmix-history', record:JSON.parse(JSON.stringify(record.value))}, window.location.origin)
  target?.postMessage({ type: 'masa-qmix-tab', tab: tab.value }, window.location.origin)
}

watch(tab, () => syncTab())
</script>

<style scoped>
.record-bar{display:flex;align-items:center;gap:10px;padding:8px 14px;background:white;border-bottom:1px solid #e6ebf1;font-size:13px}.record-bar span{margin-right:auto}
.embed-wrap {
  height: calc(100vh - 55px);
  display:flex;flex-direction:column;
  background: #f0f2f5;
}
.embed-frame {
  width: 100%;
  flex:1;
  min-height:0;
  border: none;
  display: block;
  background: #f0f2f5;
}
</style>
