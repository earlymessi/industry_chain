<template>
  <div class="embed-wrap">
    <iframe
      ref="frameRef"
      class="embed-frame"
      :src="iframeSrc"
      title="组装资源管控"
      @load="syncTab"
    />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const frameRef = ref(null)

const validTabs = ['dashboard', 'materials', 'gantt', 'charts', 'dynamic']

const tab = computed(() => {
  const value = String(route.params.tab || 'dashboard')
  return validTabs.includes(value) ? value : 'dashboard'
})

// 固定 src，避免切换侧栏时 iframe 重载导致评估结果丢失
const iframeSrc = '/masa-qmix/?embed=1'

function syncTab() {
  frameRef.value?.contentWindow?.postMessage({ type: 'masa-qmix-tab', tab: tab.value }, '*')
}

watch(tab, () => syncTab())
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
