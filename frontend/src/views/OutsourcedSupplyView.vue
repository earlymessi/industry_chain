<template>
  <div class="page">
    <el-card shadow="never" class="head-card">
      <div class="head-row">
        <div class="sub">编辑外购/外协库存数量，模拟供应商发运与到货入库</div>
        <div class="actions">
          <el-button :loading="loading" @click="loadAll">刷新</el-button>
          <el-button type="warning" :loading="simulating" @click="simulateAdvance">模拟推进 30 分钟</el-button>
          <el-button type="primary" :loading="saving" @click="saveAll">保存</el-button>
        </div>
      </div>
      <el-row :gutter="12" class="stats">
        <el-col :span="6">
          <div class="stat">
            <div class="stat-val">{{ summary.total_suppliers || 6 }}</div>
            <div class="stat-lbl">外协供应商</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat">
            <div class="stat-val">{{ summary.active_deliveries || 0 }}</div>
            <div class="stat-lbl">在途批次</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat">
            <div class="stat-val">{{ summary.pending_deliveries || 0 }}</div>
            <div class="stat-lbl">计划发运</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat warn">
            <div class="stat-val">{{ summary.shortage_alerts || 0 }}</div>
            <div class="stat-lbl">缺料预警</div>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-h">外购/外协库存</div>
      </template>
      <el-table :data="materials" size="small" stripe border>
        <el-table-column prop="name" label="物料" min-width="120" />
        <el-table-column prop="category" label="类型" width="72" />
        <el-table-column prop="supplier" label="默认供应商" min-width="130" />
        <el-table-column prop="workstation" label="目标工位" width="110" />
        <el-table-column label="现有库存" width="130">
          <template #default="{ row }">
            <el-input-number v-model="row.on_hand" :min="0" :max="99999" size="small" controls-position="right" />
          </template>
        </el-table-column>
        <el-table-column prop="in_transit_qty" label="在途数量" width="90" />
        <el-table-column prop="safety_stock" label="安全库存" width="90" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.stock_status === '缺料' ? 'danger' : row.stock_status === '紧张' ? 'warning' : row.stock_status === '在途' ? 'info' : 'success'"
            >
              {{ row.stock_status }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="head-row">
          <div class="card-h">供应商发运调度</div>
          <el-button type="primary" size="small" @click="openDispatch">新建发运</el-button>
        </div>
      </template>
      <el-table :data="deliveries" size="small" stripe border>
        <el-table-column prop="id" label="批次号" width="110" />
        <el-table-column prop="supplier_name" label="供应商" min-width="130" />
        <el-table-column label="物料" min-width="120">
          <template #default="{ row }">{{ materialName(row.material_id) }}</template>
        </el-table-column>
        <el-table-column label="数量" width="120">
          <template #default="{ row }">
            <el-input-number v-model="row.quantity" :min="0" :max="9999" size="small" controls-position="right" />
          </template>
        </el-table-column>
        <el-table-column label="预计到达(min)" width="140">
          <template #default="{ row }">
            <el-input-number v-model="row.eta_minutes" :min="0" :max="9999" size="small" controls-position="right" />
          </template>
        </el-table-column>
        <el-table-column label="优先级" width="110">
          <template #default="{ row }">
            <el-select v-model="row.priority" size="small">
              <el-option label="低" value="low" />
              <el-option label="正常" value="normal" />
              <el-option label="加急" value="urgent" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-select v-model="row.status" size="small">
              <el-option label="计划" value="planned" />
              <el-option label="在途" value="on_the_way" />
              <el-option label="已到货" value="arrived" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ $index }">
            <el-button link type="danger" @click="removeDelivery($index)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dispatchVisible" title="新建供应商发运" width="480px">
      <el-form label-width="100px">
        <el-form-item label="供应商">
          <el-select v-model="dispatchForm.supplier_name" style="width: 100%">
            <el-option v-for="s in suppliers" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="物料">
          <el-select v-model="dispatchForm.material_id" style="width: 100%">
            <el-option v-for="m in materials" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="dispatchForm.quantity" :min="1" :max="9999" />
        </el-form-item>
        <el-form-item label="预计到达">
          <el-input-number v-model="dispatchForm.eta_minutes" :min="1" :max="9999" /> 分钟
        </el-form-item>
        <el-form-item label="优先级">
          <el-select v-model="dispatchForm.priority">
            <el-option label="低" value="low" />
            <el-option label="正常" value="normal" />
            <el-option label="加急" value="urgent" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dispatchVisible = false">取消</el-button>
        <el-button type="primary" :loading="dispatching" @click="submitDispatch">发运</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'

const loading = ref(false)
const saving = ref(false)
const simulating = ref(false)
const dispatching = ref(false)
const materials = ref([])
const deliveries = ref([])
const suppliers = ref([])
const summary = ref({})
const dispatchVisible = ref(false)
const dispatchForm = ref({
  supplier_name: '',
  material_id: '',
  quantity: 20,
  eta_minutes: 20,
  priority: 'normal',
})

function materialName(id) {
  return materials.value.find((m) => m.id === id)?.name || id
}

async function loadAll() {
  loading.value = true
  try {
    const { data } = await api.get('/api/integrations/purchased-supply/state')
    materials.value = (data.materials || []).map((m) => ({ ...m }))
    deliveries.value = (data.deliveries || []).map((d) => ({ ...d }))
    suppliers.value = data.suppliers || []
    summary.value = data.summary || {}
    if (!dispatchForm.value.supplier_name && suppliers.value.length) {
      dispatchForm.value.supplier_name = suppliers.value[0]
    }
    if (!dispatchForm.value.material_id && materials.value.length) {
      dispatchForm.value.material_id = materials.value[0].id
    }
  } catch {
    ElMessage.error('加载外协状态失败')
  } finally {
    loading.value = false
  }
}

async function saveAll() {
  saving.value = true
  try {
    const payload = {
      materials: Object.fromEntries(materials.value.map((m) => [m.id, { on_hand: m.on_hand }])),
      deliveries: deliveries.value,
    }
    const { data } = await api.put('/api/integrations/purchased-supply/state', payload)
    materials.value = (data.materials || []).map((m) => ({ ...m }))
    deliveries.value = (data.deliveries || []).map((d) => ({ ...d }))
    summary.value = data.summary || {}
    ElMessage.success('已保存')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function simulateAdvance() {
  simulating.value = true
  try {
    const { data } = await api.post('/api/integrations/purchased-supply/simulate', { minutes: 30 })
    materials.value = (data.materials || []).map((m) => ({ ...m }))
    deliveries.value = (data.deliveries || []).map((d) => ({ ...d }))
    summary.value = data.summary || {}
    const n = data.simulation?.arrived_batches || 0
    ElMessage.success(n ? `已模拟到货 ${n} 批` : '暂无到期在途批次')
  } catch {
    ElMessage.error('模拟失败')
  } finally {
    simulating.value = false
  }
}

function openDispatch() {
  dispatchVisible.value = true
}

async function submitDispatch() {
  dispatching.value = true
  try {
    const { data } = await api.post('/api/integrations/purchased-supply/dispatch', dispatchForm.value)
    materials.value = (data.materials || []).map((m) => ({ ...m }))
    deliveries.value = (data.deliveries || []).map((d) => ({ ...d }))
    summary.value = data.summary || {}
    dispatchVisible.value = false
    ElMessage.success('发运已创建')
  } catch {
    ElMessage.error('发运失败')
  } finally {
    dispatching.value = false
  }
}

function removeDelivery(index) {
  deliveries.value.splice(index, 1)
}

onMounted(loadAll)
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.head-card :deep(.el-card__body) {
  padding: 16px 20px;
}

.head-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.sub {
  margin-top: 0;
  font-size: 13px;
  color: #64748b;
}

.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.stats {
  margin-top: 16px;
}

.stat {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px;
  text-align: center;
}

.stat.warn {
  background: #fff7ed;
  border-color: #fed7aa;
}

.stat-val {
  font-size: 22px;
  font-weight: 700;
  color: #0f172a;
}

.stat-lbl {
  font-size: 12px;
  color: #64748b;
  margin-top: 4px;
}

.card-h {
  font-weight: 700;
}
</style>
