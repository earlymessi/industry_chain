<template>
  <el-container class="h">
    <el-aside width="240px" class="aside">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">
          <svg class="brand-svg" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <linearGradient id="hubBrandGrad" x1="6" y1="4" x2="42" y2="44" gradientUnits="userSpaceOnUse">
                <stop stop-color="#69c0ff" />
                <stop offset="1" stop-color="#1890ff" />
              </linearGradient>
              <linearGradient id="hubBrandGlow" x1="24" y1="8" x2="24" y2="40" gradientUnits="userSpaceOnUse">
                <stop stop-color="#ffffff" stop-opacity="0.45" />
                <stop offset="1" stop-color="#ffffff" stop-opacity="0" />
              </linearGradient>
            </defs>
            <rect x="4" y="4" width="40" height="40" rx="12" fill="url(#hubBrandGrad)" fill-opacity="0.18" />
            <circle cx="24" cy="13" r="5.5" fill="url(#hubBrandGrad)" />
            <circle cx="13" cy="30" r="4.5" fill="url(#hubBrandGrad)" fill-opacity="0.88" />
            <circle cx="35" cy="30" r="4.5" fill="url(#hubBrandGrad)" fill-opacity="0.88" />
            <circle cx="24" cy="37" r="3.5" fill="url(#hubBrandGlow)" />
            <path
              d="M24 18.5V24M20.2 26.8L15.8 29.4M27.8 26.8L32.2 29.4M21.5 35H26.5"
              stroke="url(#hubBrandGrad)"
              stroke-width="2"
              stroke-linecap="round"
            />
          </svg>
        </div>
        <div class="brand-text">
          <p class="brand-title">
            产业链分布式资源<br />
            适配与调度管控系统
          </p>
        </div>
      </div>

      <div class="nav-menu">
        <div class="nav-header">产业链协同</div>
        <el-menu
          :default-active="hubActive"
          router
          class="menu"
          background-color="transparent"
          text-color="#e8eef5"
          active-text-color="#ffffff"
        >
          <el-menu-item index="/home" class="nav-item">
            <HubMenuIcon tone="hub"><HomeFilled /></HubMenuIcon>
            <span>产业链主控台</span>
          </el-menu-item>
          <el-menu-item index="/home/knowledge" class="nav-item">
            <HubMenuIcon tone="knowledge"><ChatDotRound /></HubMenuIcon>
            <span>产业链知识库</span>
          </el-menu-item>
        </el-menu>

        <div class="nav-header">系统入口</div>
        <el-menu
          ref="systemMenuRef"
          :default-active="menuActive"
          unique-opened
          router
          class="menu system-menu"
          background-color="transparent"
          text-color="#e8eef5"
          active-text-color="#ffffff"
        >
          <el-menu-item index="/home/operations-tools" class="nav-item">
            <HubMenuIcon tone="production"><FirstAidKit /></HubMenuIcon>
            <span>产业链运维系统</span>
          </el-menu-item>
          <el-sub-menu
            index="supply-chain"
            class="hub-submenu"
            :disabled="!scheduletoolAvailable"
            @open="onSupplyChainOpen"
          >
            <template #title>
              <HubMenuIcon tone="supply"><Share /></HubMenuIcon>
              <span>供应链订单调度</span>
            </template>
            <el-menu-item index="/home/supply-chain/dashboard">
              <HubMenuIcon tone="supply"><Monitor /></HubMenuIcon>
              <span>订单看板</span>
            </el-menu-item>
            <el-menu-item index="/home/supply-chain/order-input">
              <HubMenuIcon tone="supply"><EditPen /></HubMenuIcon>
              <span>信息录入</span>
            </el-menu-item>
            <el-menu-item index="/home/supply-chain/orders">
              <HubMenuIcon tone="supply"><List /></HubMenuIcon>
              <span>订单管理</span>
            </el-menu-item>
            <el-menu-item index="/home/supply-chain/params">
              <HubMenuIcon tone="supply"><Setting /></HubMenuIcon>
              <span>参数设置</span>
            </el-menu-item>
          </el-sub-menu>

          <el-sub-menu index="production" class="hub-submenu" @open="onProductionOpen">
            <template #title>
              <HubMenuIcon tone="production"><SetUp /></HubMenuIcon>
              <span>生产资源管控</span>
            </template>
            <el-menu-item index="/home/production/dashboard">
              <HubMenuIcon tone="production"><Monitor /></HubMenuIcon>
              <span>生产看板</span>
            </el-menu-item>
            <el-menu-item index="/home/production/database">
              <HubMenuIcon tone="production"><FolderOpened /></HubMenuIcon>
              <span>数据中心</span>
            </el-menu-item>
            <el-menu-item index="/home/production/aps">
              <HubMenuIcon tone="production"><Calendar /></HubMenuIcon>
              <span>智能排程</span>
            </el-menu-item>
            <el-menu-item index="/home/production/compare">
              <HubMenuIcon tone="production"><DataAnalysis /></HubMenuIcon>
              <span>方案对比</span>
            </el-menu-item>
            <el-menu-item index="/home/production/reports">
              <HubMenuIcon tone="production"><DataAnalysis /></HubMenuIcon>
              <span>分析报表</span>
            </el-menu-item>
            <el-menu-item index="/home/production/energy">
              <HubMenuIcon tone="production"><Lightning /></HubMenuIcon>
              <span>能耗管控调度</span>
            </el-menu-item>
            <el-menu-item index="/home/production/health">
              <HubMenuIcon tone="production"><FirstAidKit /></HubMenuIcon>
              <span>设备健康管控</span>
            </el-menu-item>
            <el-menu-item index="/home/production/logistics">
              <HubMenuIcon tone="production"><Van /></HubMenuIcon>
              <span>AGV物流调度</span>
            </el-menu-item>
            <el-menu-item index="/home/production/staffing">
              <HubMenuIcon tone="production"><User /></HubMenuIcon>
              <span>人员负荷调度</span>
            </el-menu-item>
            <el-menu-item index="/home/production/materials">
              <HubMenuIcon tone="production"><Box /></HubMenuIcon>
              <span>加工物料调度</span>
            </el-menu-item>
          </el-sub-menu>

          <el-sub-menu
            index="assembly"
            class="hub-submenu"
            :disabled="!assemblyAvailable"
            @open="onAssemblyOpen"
          >
            <template #title>
              <HubMenuIcon tone="assembly"><Connection /></HubMenuIcon>
              <span>组装资源管控</span>
            </template>
            <el-menu-item index="/home/assembly/dashboard">
              <HubMenuIcon tone="assembly"><Monitor /></HubMenuIcon>
              <span>组装看板</span>
            </el-menu-item>
            <el-menu-item index="/home/assembly/materials">
              <HubMenuIcon tone="assembly"><Box /></HubMenuIcon>
              <span>物料管理</span>
            </el-menu-item>
            <el-menu-item index="/home/assembly/gantt">
              <HubMenuIcon tone="assembly"><Calendar /></HubMenuIcon>
              <span>甘特图</span>
            </el-menu-item>
            <el-menu-item index="/home/assembly/charts">
              <HubMenuIcon tone="assembly"><DataAnalysis /></HubMenuIcon>
              <span>数据统计</span>
            </el-menu-item>
            <el-menu-item index="/home/assembly/dynamic">
              <HubMenuIcon tone="assembly"><VideoPlay /></HubMenuIcon>
              <span>动态演示</span>
            </el-menu-item>
          </el-sub-menu>

          <el-menu-item index="/home/outsourced-supply" class="nav-item">
            <HubMenuIcon tone="outsourced"><Van /></HubMenuIcon>
            <span>外协供应商管控</span>
          </el-menu-item>
          <el-sub-menu index="logistics-resource" class="hub-submenu" @open="onLogisticsResourceOpen">
            <template #title>
              <HubMenuIcon tone="logistics"><Guide /></HubMenuIcon>
              <span>物流资源管控</span>
            </template>
            <el-menu-item index="/home/logistics-resource/orders">
              <HubMenuIcon tone="logistics"><List /></HubMenuIcon>
              <span>订单管理</span>
            </el-menu-item>
            <el-menu-item index="/home/logistics-resource/experiment">
              <HubMenuIcon tone="logistics"><Setting /></HubMenuIcon>
              <span>实验配置</span>
            </el-menu-item>
            <el-menu-item index="/home/logistics-resource/results">
              <HubMenuIcon tone="logistics"><FolderOpened /></HubMenuIcon>
              <span>结果汇总</span>
            </el-menu-item>
            <el-menu-item index="/home/logistics-resource/charts">
              <HubMenuIcon tone="logistics"><DataAnalysis /></HubMenuIcon>
              <span>图表分析</span>
            </el-menu-item>
            <el-menu-item index="/home/logistics-resource/map">
              <HubMenuIcon tone="logistics"><Guide /></HubMenuIcon>
              <span>路径地图</span>
            </el-menu-item>
          </el-sub-menu>
        </el-menu>
      </div>

      <div class="aside-footer">
        <template v-if="activeModule === 'production'">
          数据库: <strong class="ok">已连接</strong>
        </template>
        <template v-else-if="activeModule === 'supply-chain'">Scheduletool</template>
        <template v-else-if="activeModule === 'assembly'">MASA-QMIX</template>
        <template v-else>:8008</template>
      </div>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="header-left">
          <div class="route-title">{{ pageTitle }}</div>
        </div>
        <div class="header-right">
          <div v-if="moduleStatusLabel" class="system-status">
            <span class="status-dot" :class="moduleStatusOnline ? 'on' : 'off'" />
            <span :class="moduleStatusOnline ? 'text-success' : 'text-warn'">{{ moduleStatusLabel }}</span>
          </div>
          <div class="system-time">
            <el-icon><Clock /></el-icon>
            <span>{{ currentTime }}</span>
          </div>
          <div class="user">
            <div class="avatar">OP</div>
            <div class="user-name">管理员</div>
          </div>
          <el-button
            v-if="activeModule === 'production'"
            type="primary"
            class="assistant-trigger"
            @click="assistantStore.open()"
          >
            <el-icon><ChatDotRound /></el-icon>
            智能助手
          </el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>

    <el-drawer
      v-model="assistantStore.visible"
      title="智能助手"
      size="520px"
      direction="rtl"
      class="global-assistant-drawer"
    >
      <AgentChatPanel compact :show-header="false" />
    </el-drawer>
  </el-container>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Monitor,
  Connection,
  Clock,
  HomeFilled,
  ChatDotRound,
  Share,
  Van,
  FolderOpened,
  Calendar,
  DataAnalysis,
  Lightning,
  FirstAidKit,
  User,
  Box,
  EditPen,
  List,
  Setting,
  VideoPlay,
  Guide,
  SetUp,
} from '@element-plus/icons-vue'
import { api } from '../api/client'
import AgentChatPanel from '../components/AgentChatPanel.vue'
import HubMenuIcon from '../components/HubMenuIcon.vue'
import { useAssistantStore } from '../stores/useAssistantStore'

const route = useRoute()
const router = useRouter()
const assistantStore = useAssistantStore()

const activeModule = computed(() => {
  if (route.path.startsWith('/home/production')) return 'production'
  if (route.path.startsWith('/home/supply-chain')) return 'supply-chain'
  if (route.path.startsWith('/home/assembly')) return 'assembly'
  if (route.path.startsWith('/home/logistics-resource')) return 'logistics-resource'
  if (route.path.startsWith('/home/operations-tools')) return 'operations'
  return ''
})

const systemMenuRef = ref(null)
const MODULE_MENU_KEYS = ['production', 'supply-chain', 'assembly', 'logistics-resource']

async function syncSystemMenuOpen() {
  await nextTick()
  const menu = systemMenuRef.value
  if (!menu) return
  const module = activeModule.value
  if (module && MODULE_MENU_KEYS.includes(module)) {
    menu.open(module)
  } else {
    MODULE_MENU_KEYS.forEach((key) => menu.close(key))
  }
}

watch(activeModule, syncSystemMenuOpen, { flush: 'post' })

const hubActive = computed(() => {
  if (activeModule.value) return ''
  if (route.path.startsWith('/home/')) return route.path
  return ''
})

const menuActive = computed(() => route.path)

const routeTitleMap = {
  '/home/operations-tools': '产业链运维系统',
  '/home/production/dashboard': '生产看板',
  '/home/production/database': '数据中心',
  '/home/production/aps': '智能排程',
  '/home/production/compare': '方案对比',
  '/home/production/assistant': '智能助手',
  '/home/production/reports': '分析报表',
  '/home/production/energy': '能耗管控调度',
  '/home/production/health': '设备健康管控',
  '/home/production/logistics': 'AGV物流调度',
  '/home/production/staffing': '人员负荷调度',
  '/home/production/materials': '加工物料调度',
  '/home/supply-chain/dashboard': '订单看板',
  '/home/supply-chain/order-input': '信息录入',
  '/home/supply-chain/orders': '订单管理',
  '/home/supply-chain/params': '参数设置',
  '/home/assembly/dashboard': '组装看板',
  '/home/assembly/materials': '物料管理',
  '/home/assembly/gantt': '甘特图',
  '/home/assembly/charts': '数据统计',
  '/home/assembly/dynamic': '动态演示',
  '/home/logistics-resource/orders': '物流资源管控 · 订单管理',
  '/home/logistics-resource/experiment': '物流资源管控 · 实验配置',
  '/home/logistics-resource/results': '物流资源管控 · 结果汇总',
  '/home/logistics-resource/charts': '物流资源管控 · 图表分析',
  '/home/logistics-resource/map': '物流资源管控 · 路径地图',
}

const pageTitle = computed(() => {
  if (routeTitleMap[route.path]) return routeTitleMap[route.path]
  if (route.path.includes('/knowledge')) return '家电产业链知识库'
  if (route.path.includes('/outsourced-supply')) return '外协供应商管控'
  if (route.path.includes('/logistics-resource')) return '物流资源管控'
  return '产业链主控台'
})

const moduleStatusLabel = computed(() => {
  if (activeModule.value === 'production') return 'MongoDB Online'
  if (activeModule.value === 'supply-chain') return scheduletoolAvailable.value ? 'Scheduletool 在线' : 'Scheduletool 离线'
  if (activeModule.value === 'assembly') return assemblyAvailable.value ? '组装模块在线' : '组装模块离线'
  return ''
})

const moduleStatusOnline = computed(() => {
  if (activeModule.value === 'production') return true
  if (activeModule.value === 'supply-chain') return scheduletoolAvailable.value
  if (activeModule.value === 'assembly') return assemblyAvailable.value
  return false
})

const assemblyAvailable = ref(false)
const scheduletoolAvailable = ref(false)

const currentTime = ref('')
let timer = null
let versionTimer = null

function tick() {
  currentTime.value = new Date().toLocaleString()
}

function onProductionOpen() {
  if (!route.path.startsWith('/home/production')) {
    router.push('/home/production/dashboard')
  }
}

function onSupplyChainOpen() {
  if (!scheduletoolAvailable.value) return
  if (!route.path.startsWith('/home/supply-chain')) {
    router.push('/home/supply-chain/dashboard')
  }
}

function onAssemblyOpen() {
  if (!assemblyAvailable.value) return
  if (!route.path.startsWith('/home/assembly')) {
    router.push('/home/assembly/dashboard')
  }
}

function onLogisticsResourceOpen() {
  if (activeModule.value !== 'logistics-resource') {
    router.push('/home/logistics-resource/experiment')
  }
}

async function checkAssembly() {
  try {
    const { data } = await api.get('/api/integrations/masa-qmix')
    assemblyAvailable.value = !!data?.available
  } catch {
    assemblyAvailable.value = false
  }
}

async function checkScheduletool() {
  try {
    const { data } = await api.get('/api/integrations/scheduletool/status')
    scheduletoolAvailable.value = !!(data?.mounted || data?.available)
  } catch {
    scheduletoolAvailable.value = false
  }
}

async function checkFrontendVersion() {
  try {
    const resp = await fetch('/api/frontend-version', { cache: 'no-store' })
    if (!resp.ok) return
    const data = await resp.json()
    const version = data?.version
    const serverInstance = data?.server_instance
    if (!version || version === 'missing') return
    const runtimeVersion = `${version}:${serverInstance || 'server'}`
    const key = 'metaforge_runtime_version'
    const previous = localStorage.getItem(key)
    if (previous && previous !== runtimeVersion) {
      localStorage.setItem(key, runtimeVersion)
      window.location.reload()
      return
    }
    localStorage.setItem(key, runtimeVersion)
  } catch {
    // ignore
  }
}

function handleVisibilityChange() {
  if (!document.hidden) checkFrontendVersion()
}

onMounted(() => {
  tick()
  timer = setInterval(tick, 1000)
  checkAssembly()
  checkScheduletool()
  checkFrontendVersion()
  versionTimer = setInterval(checkFrontendVersion, 15000)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  syncSystemMenuOpen()
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (versionTimer) clearInterval(versionTimer)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<style scoped>
.h { height: 100vh; }

.aside {
  background: #202d3d;
  color: #e8eef5;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.brand {
  min-height: 80px;
  padding: 14px 10px;
  display: flex;
  align-items: center;
  gap: 10px;
  background: linear-gradient(135deg, #001529 0%, #003a63 52%, #002140 100%);
  color: #fff;
  border-bottom: 1px solid rgba(105, 192, 255, 0.18);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
  position: relative;
  overflow: hidden;
}

.brand::after {
  content: '';
  position: absolute;
  top: -28px;
  right: -20px;
  width: 88px;
  height: 88px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(24, 144, 255, 0.14) 0%, rgba(24, 144, 255, 0) 70%);
  pointer-events: none;
  z-index: 0;
}

.brand-mark {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  position: relative;
  z-index: 1;
}

.brand-svg {
  width: 100%;
  height: 100%;
  display: block;
  filter: drop-shadow(0 1px 4px rgba(24, 144, 255, 0.22));
}

.brand-text {
  flex: 1;
  min-width: 0;
  position: relative;
  z-index: 1;
}

.brand-title {
  margin: 0;
  padding: 0;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.4;
  letter-spacing: 0;
  color: #ffffff;
  font-family: inherit;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

.nav-header {
  font-size: 11px;
  color: #8b9bb0;
  padding: 15px 20px 5px;
  font-weight: 600;
  letter-spacing: 0.5px;
}
.nav-menu {
  flex: 1;
  padding-top: 10px;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: thin;
  scrollbar-color: #3a4f66 transparent;
}
.nav-menu::-webkit-scrollbar { width: 4px; }
.nav-menu::-webkit-scrollbar-thumb { background: #3a4f66; border-radius: 4px; }
.nav-menu::-webkit-scrollbar-track { background: transparent; }
.menu { border-right: none; background: transparent; }

:deep(.el-menu) { border-right: none; }
:deep(.el-menu-item) {
  height: auto;
  line-height: normal;
  padding: 12px 20px;
  color: #e8eef5;
  font-size: 15px;
  font-weight: 400;
  border-left: 4px solid transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
}
:deep(.el-menu-item:hover) {
  background: #263445 !important;
  color: #ffffff !important;
}
:deep(.el-menu-item.is-active) {
  background: #1890ff !important;
  color: #ffffff !important;
  border-left-color: #1890ff;
}
:deep(.el-menu-item.is-disabled),
:deep(.el-sub-menu.is-disabled > .el-sub-menu__title) {
  opacity: 0.45;
  cursor: not-allowed;
}

:deep(.system-menu.el-menu) { border-right: none; }

:deep(.hub-submenu > .el-sub-menu__title) {
  height: auto;
  line-height: normal;
  padding: 12px 20px;
  color: #e8eef5;
  font-size: 15px;
  font-weight: 400;
  border-left: 4px solid transparent;
  transition: background-color 0.22s ease, color 0.22s ease;
  display: flex;
  align-items: center;
}
:deep(.hub-submenu > .el-sub-menu__title:hover) {
  background: #263445 !important;
  color: #ffffff !important;
}
:deep(.hub-submenu.is-open > .el-sub-menu__title) {
  color: #ffffff;
  background: #263445;
}
:deep(.hub-submenu .el-sub-menu__icon-arrow) {
  color: #e8eef5;
  transition: transform 0.34s cubic-bezier(0.22, 1, 0.36, 1);
}

:deep(.hub-submenu .el-collapse-transition-enter-active),
:deep(.hub-submenu .el-collapse-transition-leave-active) {
  transition:
    max-height 0.34s cubic-bezier(0.22, 1, 0.36, 1),
    padding-top 0.34s cubic-bezier(0.22, 1, 0.36, 1),
    padding-bottom 0.34s cubic-bezier(0.22, 1, 0.36, 1);
}

:deep(.hub-submenu > .el-menu--inline) {
  background: #1e2a38 !important;
  border-top: 1px solid #2c3b4e;
  padding: 2px 0 4px;
}

:deep(.hub-submenu.is-open .el-menu--inline .el-menu-item) {
  animation: hub-submenu-item-in 0.3s cubic-bezier(0.22, 1, 0.36, 1) both;
}
:deep(.hub-submenu.is-open .el-menu--inline .el-menu-item:nth-child(1)) { animation-delay: 0.03s; }
:deep(.hub-submenu.is-open .el-menu--inline .el-menu-item:nth-child(2)) { animation-delay: 0.05s; }
:deep(.hub-submenu.is-open .el-menu--inline .el-menu-item:nth-child(3)) { animation-delay: 0.07s; }
:deep(.hub-submenu.is-open .el-menu--inline .el-menu-item:nth-child(4)) { animation-delay: 0.09s; }
:deep(.hub-submenu.is-open .el-menu--inline .el-menu-item:nth-child(5)) { animation-delay: 0.11s; }
:deep(.hub-submenu.is-open .el-menu--inline .el-menu-item:nth-child(6)) { animation-delay: 0.13s; }
:deep(.hub-submenu.is-open .el-menu--inline .el-menu-item:nth-child(7)) { animation-delay: 0.15s; }
:deep(.hub-submenu.is-open .el-menu--inline .el-menu-item:nth-child(8)) { animation-delay: 0.17s; }
:deep(.hub-submenu.is-open .el-menu--inline .el-menu-item:nth-child(9)) { animation-delay: 0.19s; }

@keyframes hub-submenu-item-in {
  from {
    opacity: 0;
    transform: translateY(-6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

:deep(.system-menu .el-menu--inline .el-menu-item) {
  padding: 12px 20px 12px 44px !important;
  font-size: 15px;
  font-weight: 400;
  min-height: auto;
  color: #e8eef5 !important;
  background: transparent;
  border-left: 4px solid transparent;
}
:deep(.system-menu .el-menu--inline .el-menu-item:hover) {
  background: #263445 !important;
  color: #ffffff !important;
}
:deep(.system-menu .el-menu--inline .el-menu-item.is-active) {
  background: #1890ff !important;
  color: #ffffff !important;
  border-left-color: #1890ff;
}

.aside-footer {
  padding: 12px 16px;
  font-size: 12px;
  color: #909399;
  border-top: 1px solid #34495e;
}
.ok { color: #67c23a; }

.header {
  height: 55px;
  background: #ffffff;
  border-bottom: 1px solid #dcdfe6;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}

.header-left { display: flex; align-items: center; gap: 12px; }
.route-title { margin: 0; font-weight: 700; color: #303133; font-size: 15px; }
.header-right { display: flex; align-items: center; gap: 18px; color: #606266; font-size: 13px; }
.system-status { display: flex; align-items: center; gap: 8px; }
.status-dot {
  height: 8px;
  width: 8px;
  border-radius: 50%;
  display: inline-block;
  background-color: #67c23a;
}
.status-dot.off { background-color: #e6a23c; }
.text-success { color: #67c23a; }
.text-warn { color: #e6a23c; }
.system-time { display: flex; align-items: center; gap: 6px; color: #909399; }
.user { display: flex; align-items: center; gap: 8px; }
.avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}
.user-name { font-weight: 600; font-size: 13px; color: #606266; }
.assistant-trigger { margin-left: 4px; }

:deep(.global-assistant-drawer .el-drawer__body) {
  padding: 12px 16px 16px;
  display: flex;
  flex-direction: column;
  height: calc(100% - 56px);
}
:deep(.global-assistant-drawer .chat-panel) { flex: 1; min-height: 0; }
:deep(.global-assistant-drawer .messages) { max-height: none; flex: 1; }

.main { background: #f0f2f5; }
</style>
