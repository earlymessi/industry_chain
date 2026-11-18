<template>
  <div class="embed-wrap" v-loading="loading">
    <div v-if="record" class="record-bar"><span>已加载：{{record.name}} · {{timeMapping}}</span><el-button size="small" @click="clearRecord">返回当前结果</el-button><el-button size="small" @click="router.push('/home/logistics-resource/database')">数据中心</el-button></div>
    <el-result v-if="error" icon="warning" title="车辆路径模块暂不可用" :sub-title="error">
      <template #extra><el-button type="primary" @click="checkModule">重新检查</el-button></template>
    </el-result>
    <iframe
      v-else-if="!loading"
      ref="frameRef"
      class="embed-frame"
      :src="iframeSrc"
      title="多周期车辆路径优化"
      @load="syncTab"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import {ElMessage} from 'element-plus'

const route = useRoute()
const router = useRouter()
const tabs = ['orders', 'experiment', 'results', 'charts', 'map']
const tab = computed(() => tabs.includes(route.params.tab) ? route.params.tab : 'experiment')
const frameRef = ref(null)
const loading = ref(true)
const error = ref('')
// 子页切换通过消息同步，保留已填写的参数与运行进度。
const record=ref(null)
const timeMapping=computed(()=>{const config=record.value?.payload?.chain_config;if(!config)return '历史快照';const day=Math.floor((Number(config.delivery_origin_at)-Number(config.start_at))/86400)+1;return `配送第${record.value.payload.route?.route?.day || 1}天 → 全链第${day}天`})
let revision=0
async function loadRecord(key){const turn=++revision;if(!key){record.value=null;return}try{const {data}=await api.get(`/api/operations-tools/data-center/delivery/${encodeURIComponent(key)}`);if(turn===revision)record.value=data}catch(e){if(turn===revision)ElMessage.error(String(e.response?.data?.detail||'历史结果加载失败'))}}
function clearRecord(){const query={...route.query};delete query.record;router.replace({path:route.path,query})}
watch(()=>route.query.record,key=>loadRecord(key),{immediate:true})
const initialTab = tab.value
const iframeSrc = computed(() => `/logistics-vrp/?embed=1&tab=${initialTab}${record.value ? '&record=' + encodeURIComponent(record.value.id) : ''}`)

function syncTab() {
  frameRef.value?.contentWindow?.postMessage({ type: 'zhenjie-tab', tab: tab.value }, window.location.origin)
}

function handleMessage(event) {
  if (event.origin !== window.location.origin || event.source !== frameRef.value?.contentWindow) return
  if (event.data?.type === 'zhenjie-ready') syncTab()
  if (event.data?.type === 'zhenjie-tab-changed' && tabs.includes(event.data.tab) && event.data.tab !== tab.value) {
    router.replace({path:`/home/logistics-resource/${event.data.tab}`, query:record.value ? {record:record.value.id} : {}})
  }
}

async function checkModule() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get('/api/integrations/zhenjie/status')
    if (!data.mounted) error.value = data.detail || '请安装 zhenjie/requirements.txt 中的依赖并重启后端。'
  } catch (err) {
    if (err.response?.status === 404) {
      error.value = '当前后端尚未加载车辆路径接口，请重启项目后端后点击“重新检查”。'
    } else {
      error.value = err.response?.data?.detail || '无法连接车辆路径模块，请检查后端服务。'
    }
  } finally {
    loading.value = false
  }
}

watch(tab, syncTab)
onMounted(() => {
  window.addEventListener('message', handleMessage)
  checkModule()
})
onUnmounted(() => window.removeEventListener('message', handleMessage))
</script>

<style scoped>
.record-bar{display:flex;align-items:center;gap:10px;padding:8px 14px;background:white;border-bottom:1px solid #e6ebf1;font-size:13px}.record-bar span{margin-right:auto}
.embed-wrap { height: calc(100vh - 55px); display:flex; flex-direction:column; background: #f0f2f5; }
.embed-frame { width: 100%; flex:1; min-height:0; border: none; display: block; }
</style>
