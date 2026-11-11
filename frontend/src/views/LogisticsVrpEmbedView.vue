<template>
  <div class="embed-wrap" v-loading="loading">
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

const route = useRoute()
const router = useRouter()
const tabs = ['orders', 'experiment', 'results', 'charts', 'map']
const tab = computed(() => tabs.includes(route.params.tab) ? route.params.tab : 'experiment')
const frameRef = ref(null)
const loading = ref(true)
const error = ref('')
// 子页切换通过消息同步，保留已填写的参数与运行进度。
const iframeSrc = `/logistics-vrp/?embed=1&tab=${tab.value}`

function syncTab() {
  frameRef.value?.contentWindow?.postMessage({ type: 'zhenjie-tab', tab: tab.value }, window.location.origin)
}

function handleMessage(event) {
  if (event.origin !== window.location.origin || event.source !== frameRef.value?.contentWindow) return
  if (event.data?.type === 'zhenjie-ready') syncTab()
  if (event.data?.type === 'zhenjie-tab-changed' && tabs.includes(event.data.tab) && event.data.tab !== tab.value) {
    router.replace(`/home/logistics-resource/${event.data.tab}`)
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
.embed-wrap { height: calc(100vh - 55px); background: #f0f2f5; }
.embed-frame { width: 100%; height: 100%; border: none; display: block; }
</style>
