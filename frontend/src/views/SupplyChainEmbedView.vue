<template>
  <div class="embed-wrap">
    <iframe
      ref="frameRef"
      class="embed-frame"
      :src="iframeSrc"
      title="供应链订单看板"
      @load="onFrameLoad"
    />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const frameRef = ref(null)
const frameReady = ref(false)

const TAB_MAP = {
  dashboard: { tab: 'dashboard' },
  'order-input': { tab: 'orderInput' },
  orders: { tab: 'orderManagement' },
  params: { tab: 'params' },
  pareto: { tab: 'dashboard', options: { focus: 'pareto' } },
}

const validTabs = Object.keys(TAB_MAP)

const tab = computed(() => {
  const value = String(route.params.tab || 'dashboard')
  return validTabs.includes(value) ? value : 'dashboard'
})

const iframeSrc = '/scheduletool/schedulePage/dataShow?embed=1'

function syncTab() {
  if (!frameReady.value) return
  const mapping = TAB_MAP[tab.value] || TAB_MAP.dashboard
  const payload = {
    type: 'scheduletool-tab',
    tab: mapping.tab,
    options: mapping.options || {},
  }
  const win = frameRef.value?.contentWindow
  if (!win) return
  win.postMessage(payload, '*')
}

function onFrameLoad() {
  frameReady.value = true
  syncTab()
  setTimeout(syncTab, 200)
  setTimeout(syncTab, 600)
}

watch(tab, () => {
  syncTab()
  setTimeout(syncTab, 150)
})
</script>

<style scoped>
.embed-wrap {
  height: calc(100vh - 55px);
  background: #f0f2f5;
}
.embed-frame {
  width: 100%;
  height: 100%;
  border: none;
  display: block;
  background: #f0f2f5;
}
</style>
