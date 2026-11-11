<template>
  <div class="page">
    <el-card shadow="never" class="panorama-card">
      <div class="panorama-toolbar">
        <el-button link type="primary" :loading="refreshing" @click="refreshAll">刷新</el-button>
      </div>
      <SupplyChainPanorama
        :pareto-count="scheduleSummary.pareto_solution_count || 0"
        :batch-order-count="scheduleSummary.last_batch_order_count || 0"
        :reference-etpt-h="scheduleSummary.reference_etpt_h"
        :reference-tc="scheduleSummary.reference_tc"
        :kdcea-status="scheduleSummary.kdcea_status || 'idle'"
        :has-reference-plan="!!scheduleSummary.has_reference_plan"
        :assembly-available="assemblyOk"
        :supplier-performance="supplyChain?.supplier_performance || []"
        :in-transit-count="supplySummary?.active_deliveries || 0"
        :shortage-count="supplySummary?.shortage_alerts || 0"
        :execution-status="execution.status || 'idle'"
        :readiness-status="readiness?.status || ''"
        @navigate="go"
      />
    </el-card>

    <el-card shadow="never" class="kitting-card">
      <template #header>
        <div class="row">
          <div class="h">当前批次齐套明细</div>
          <div class="row-actions">
            <el-button link type="primary" @click="go('/home/outsourced-supply')">外协调度</el-button>
            <el-tag v-if="readiness" :type="readiness.status === 'ready' ? 'success' : 'info'" size="small">
            {{ readiness.status === 'ready' ? '待组装' : '已消费' }}
            </el-tag>
          </div>
        </div>
      </template>
      <template v-if="readiness">
        <el-descriptions :column="4" border size="small" class="mb12">
          <el-descriptions-item label="来源计划">{{ readiness.plan_name }}</el-descriptions-item>
          <el-descriptions-item label="可组装台数">{{ readiness.product_units }} 台</el-descriptions-item>
          <el-descriptions-item label="MES Makespan">{{ readiness.mes_makespan_h }} h</el-descriptions-item>
          <el-descriptions-item label="完工时间">{{ formatTime(readiness.mes_completed_at) }}</el-descriptions-item>
        </el-descriptions>
        <el-row :gutter="16">
          <el-col :lg="12" :span="24">
            <div class="kitting-block">
              <div class="kitting-title self">自制件</div>
              <el-table :data="selfMadeOverview" size="small" max-height="260" stripe>
                <el-table-column prop="job_name" label="生产工件" min-width="140" />
                <el-table-column prop="mapped_part_name" label="组装物料" min-width="120" />
                <el-table-column prop="workstation" label="目标工位" width="100" />
              </el-table>
            </div>
          </el-col>
          <el-col :lg="12" :span="24">
            <div class="kitting-block">
              <div class="kitting-title purchased">外购/外协件</div>
              <el-table :data="purchasedOverview" size="small" max-height="260" stripe>
                <el-table-column prop="name" label="物料" min-width="100" />
                <el-table-column prop="category" label="类型" width="72" />
                <el-table-column prop="supplier" label="供应商" min-width="110" />
                <el-table-column prop="workstation" label="工位" width="96" />
                <el-table-column prop="on_hand" label="库存" width="64" />
                <el-table-column prop="in_transit_qty" label="在途" width="64" />
                <el-table-column prop="stock_status" label="状态" width="72">
                  <template #default="{ row }">
                    <el-tag
                      size="small"
                      :type="row.stock_status === '缺料' ? 'danger' : row.stock_status === '在途' ? 'warning' : 'success'"
                    >
                      {{ row.stock_status }}
                    </el-tag>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </el-col>
        </el-row>
      </template>
      <el-empty v-else :image-size="64" />
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import SupplyChainPanorama from '../components/SupplyChainPanorama.vue'

const router = useRouter()
const refreshing = ref(false)
const readiness = ref(null)
const execution = ref({ status: 'idle' })
const supplyChain = ref(null)
const purchasedCatalog = ref({ parts: [] })
const scheduleSummary = ref({})
const assemblyOk = ref(false)

const supplySummary = computed(() => supplyChain.value?.summary || null)

const selfMadeOverview = computed(() => {
  const parts = readiness.value?.self_made_parts || []
  const byJob = {}
  parts.forEach((p) => {
    const name = p.job_name || '未知工件'
    if (!byJob[name]) {
      byJob[name] = { job_name: name, parts: [], workstation: p.mapped_workstation }
    }
    byJob[name].parts.push(p.mapped_part_name)
  })
  return Object.values(byJob).map((row) => ({
    job_name: row.job_name,
    mapped_part_name: row.parts.join('、'),
    workstation: row.workstation,
  }))
})

const purchasedOverview = computed(() => {
  const overview = supplyChain.value?.materials_overview
  if (overview?.length) {
    return overview.map((part) => ({
      ...part,
      supplier: part.supplier,
    }))
  }
  const catalog = purchasedCatalog.value?.parts?.length
    ? purchasedCatalog.value.parts
    : readiness.value?.purchased_parts || []
  const inTransit = supplyChain.value?.in_transit || []
  const shortages = (supplyChain.value?.critical_shortages || []).reduce((acc, s) => {
    acc[s.material] = s
    return acc
  }, {})
  const transitByMaterial = {}
  inTransit.forEach((item) => {
    const key = item.material
    if (!transitByMaterial[key]) {
      transitByMaterial[key] = { qty: 0, supplier: item.supplier_name }
    }
    transitByMaterial[key].qty += item.quantity || 0
  })
  return catalog.map((part) => {
    const transit = transitByMaterial[part.id] || {}
    const shortage = shortages[part.id]
    let stockStatus = '充足'
    if (shortage) stockStatus = shortage.severity === 'high' ? '缺料' : '紧张'
    else if (transit.qty) stockStatus = '在途'
    return {
      ...part,
      supplier: transit.supplier || part.supplier,
      stock_status: stockStatus,
    }
  })
})

function formatTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

function go(path) {
  router.push(path)
}

async function loadReadiness() {
  try {
    const { data } = await api.get('/api/integrations/readiness/last')
    readiness.value = data
  } catch {
    readiness.value = null
  }
}

async function loadExecution() {
  try {
    const { data } = await api.get('/api/execution/state')
    execution.value = data || { status: 'idle' }
  } catch {
    execution.value = { status: 'idle' }
  }
}

async function loadSupplyChain() {
  try {
    const { data } = await api.get('/api/integrations/supply-chain/status')
    supplyChain.value = data?.data || data
  } catch {
    try {
      const { data } = await api.get('/masa-qmix/api/supply-chain/status')
      supplyChain.value = data?.data || data
    } catch {
      supplyChain.value = null
    }
  }
}

async function loadPurchasedCatalog() {
  try {
    const { data } = await api.get('/api/integrations/purchased-parts/catalog')
    purchasedCatalog.value = data
  } catch {
    purchasedCatalog.value = { parts: readiness.value?.purchased_parts || [] }
  }
}

async function loadScheduleSummary() {
  try {
    const { data } = await api.get('/api/integrations/scheduletool/summary')
    scheduleSummary.value = data || {}
  } catch {
    scheduleSummary.value = {}
  }
}

async function loadModuleFlags() {
  try {
    const { data } = await api.get('/api/integrations/masa-qmix')
    assemblyOk.value = !!data?.available
  } catch {
    assemblyOk.value = false
  }
}

async function refreshAll() {
  refreshing.value = true
  try {
    await Promise.all([
      loadExecution(),
      loadReadiness(),
      loadSupplyChain(),
      loadPurchasedCatalog(),
      loadScheduleSummary(),
      loadModuleFlags(),
    ])
  } finally {
    refreshing.value = false
  }
}

onMounted(refreshAll)
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panorama-card :deep(.el-card__body) {
  padding: 8px 12px 12px;
  position: relative;
}

.panorama-toolbar {
  position: absolute;
  top: 8px;
  right: 12px;
  z-index: 2;
}

.kitting-card :deep(.el-card__body) {
  padding-top: 12px;
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.h {
  font-weight: 700;
}

.mb12 {
  margin-bottom: 12px;
}

.kitting-block {
  margin-bottom: 12px;
}

.kitting-title {
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 8px;
  padding-left: 10px;
  border-left: 3px solid #cbd5e1;
}

.kitting-title.self {
  border-left-color: #3b82f6;
  color: #1d4ed8;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.kitting-title.purchased {
  border-left-color: #22c55e;
  color: #15803d;
}
</style>
