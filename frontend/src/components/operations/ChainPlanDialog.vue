<template>
  <el-dialog v-model="opened" title="计划衔接" width="min(1050px, 96vw)" :close-on-click-modal="false">
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-tabs v-model="tab">
      <el-tab-pane label="1 选择计划" name="sources">
        <div class="chain-grid">
          <el-form label-position="top">
            <el-form-item label="执行计划名称"><el-input v-model="config.name" /></el-form-item>
            <el-form-item label="生产：库内已排程计划"><el-select v-model="config.production.plan_id" filterable class="full" @change="selectProduction"><el-option v-for="p in productions" :key="p.id" :value="p.id" :label="p.name" /></el-select></el-form-item>
            <div class="chain-grid"><el-form-item label="保存算法"><el-select v-model="config.production.solver_id" class="full"><el-option v-for="s in selectedProduction?.solvers || []" :key="s" :value="s" :label="s.toUpperCase()" /></el-select></el-form-item><el-form-item label="原生产时间单位"><el-select v-model="config.production.time_unit" class="full"><el-option value="hours" label="小时" /><el-option value="minutes" label="分钟" /><el-option value="seconds" label="秒" /></el-select></el-form-item></div>
            <el-form-item label="生产第0时刻对应的北京时间"><input v-model="startLocal" type="datetime-local" class="date-input" /></el-form-item>
            <el-button :loading="reading" :disabled="!config.production.plan_id" @click="readProduction">读取工单，关联部件 →</el-button>
          </el-form>
          <el-form label-position="top">
            <el-form-item label="本批组装数量（台）"><el-input-number v-model="config.units" :min="1" :max="100" :precision="0" /></el-form-item>
            <el-form-item label="组装来源"><el-radio-group v-model="config.assembly_mode"><el-radio value="supplement">按原工艺补排</el-radio><el-radio value="saved">已保存QMIX评估</el-radio></el-radio-group></el-form-item>
            <template v-if="config.assembly_mode === 'saved'"><el-form-item label="具体评估结果（批量须一致）"><el-select v-model="config.assembly_id" class="full"><el-option v-for="r in catalog.assembly?.results || []" :key="r.id" :value="r.id" :label="r.name" :disabled="r.units !== config.units" /></el-select></el-form-item><el-form-item label="评估第0时刻对应的北京时间"><input v-model="assemblyLocal" type="datetime-local" class="date-input" /></el-form-item><el-form-item label="确认评估时间单位"><el-select v-model="config.assembly_time_unit" class="full"><el-option value="minutes" label="分钟" /><el-option value="seconds" label="秒" /><el-option value="hours" label="小时" /></el-select></el-form-item></template>
            <p v-else class="hint">复用原9工序、18工位和标准工时，按齐套与资源空档生成具体安排。</p>
            <p v-if="catalog.assembly?.messages?.length" class="hint">{{ catalog.assembly.messages[0] }}</p>
            <el-form-item label="配送来源"><el-radio-group v-model="config.delivery_mode"><el-radio value="saved">已保存车辆路线</el-radio><el-radio value="unbound">暂不绑定</el-radio></el-radio-group></el-form-item>
            <template v-if="config.delivery_mode === 'saved'"><el-select v-model="config.route_id" filterable class="full" placeholder="选择本批配送路线" @change="readRoute"><el-option v-for="r in catalog.routes || []" :key="r.id" :value="r.id" :label="r.name" /></el-select><p v-if="route" class="hint">原客户：{{ route.customers.map(c => `${c.cust_name || c.cust_id} ${c.demand}件`).join('；') }}。合计 {{ routeQuantity }} 件，须与组装数量一致。</p><div class="chain-grid"><el-form-item label="该路线当天对应日期"><input v-model="config.delivery_date" type="date" class="date-input" /></el-form-item><el-form-item label="确认车辆额定容量（件）"><el-input-number v-model="config.vehicle_capacity" :min="1" /></el-form-item></div><el-checkbox v-model="config.customer_windows_hard">将原软收货窗口设为硬约束</el-checkbox><el-collapse v-if="route"><el-collapse-item title="客户收货窗口 / 交付承诺（可补充）"><div v-for="c in route.customers" :key="c.cust_id" class="customer-commitment"><span>{{ c.cust_name || c.cust_id }} · {{ c.demand }}件<br />窗口 {{ routeWindow(c) }}</span><input type="datetime-local" class="date-input" :value="localTime(config.customer_commitments[String(Number(c.cust_id))])" @input="config.customer_commitments[String(Number(c.cust_id))] = parseLocal($event.target.value)" /></div><p class="hint">交付承诺可留空，留空显示交期待确认；不会用收货窗口代填。</p></el-collapse-item></el-collapse></template>
          </el-form>
        </div>
      </el-tab-pane>
      <el-tab-pane label="2 部件与交接" name="binding">
        <p class="hint">勾选本批组装需要的工单，明确“整批产出多少件”和“每台用多少”。未标件数的生产批次不会自动当成1件。</p>
        <el-table :data="config.parts" size="small" max-height="260" empty-text="先在第1步读取生产工单">
          <el-table-column label="采用" width="58"><template #default="{row}"><el-checkbox v-model="row.enabled" /></template></el-table-column>
          <el-table-column prop="name" label="自制部件 / 来源工单" min-width="170" />
          <el-table-column label="整批产出件数" width="145"><template #default="{row}"><el-input-number v-model="row.produced_quantity" :min="0.001" size="small" controls-position="right" /></template></el-table-column>
          <el-table-column label="每台用量" width="135"><template #default="{row}"><el-input-number v-model="row.per_unit" :min="0.001" size="small" controls-position="right" /></template></el-table-column>
          <el-table-column label="消耗工序" width="145"><template #default="{row}"><el-select v-model="row.process_id" size="small"><el-option v-for="p in catalog.processes" :key="p.id" :value="p.id" :label="p.name" /></el-select></template></el-table-column>
        </el-table>
        <el-collapse class="extras"><el-collapse-item title="外购件用量、可用库存与到货" name="materials">
          <el-table :data="config.purchased" size="small" max-height="290">
            <el-table-column label="采用" width="58"><template #default="{row}"><el-checkbox v-model="row.enabled" /></template></el-table-column><el-table-column prop="name" label="外购件" min-width="130" />
            <el-table-column label="每台用量" width="145"><template #default="{row}"><el-input-number v-model="row.per_unit" :min="0.001" size="small" controls-position="right" /></template></el-table-column>
            <el-table-column label="本次可用库存" width="145"><template #default="{row}"><el-input-number v-model="config.stock_overrides[row.material_id]" :min="0" size="small" controls-position="right" /></template></el-table-column>
            <el-table-column label="消耗工序" width="145"><template #default="{row}"><el-select v-model="row.process_id" size="small"><el-option v-for="p in catalog.processes" :key="p.id" :value="p.id" :label="p.name" /></el-select></template></el-table-column>
          </el-table>
          <p class="hint">库存读取现有供给快照，可核对后调整；已到货批次不重复加入库存。每台用量1为待核对建议。</p>
          <div v-for="d in pendingDeliveries" :key="d.id" class="arrival"><span>{{ d.supplier_name }} · {{ d.material_id }} · {{ d.quantity }}件</span><input type="datetime-local" class="date-input" :value="localTime(config.arrival_overrides[d.id])" @input="config.arrival_overrides[d.id] = parseLocal($event.target.value)" /></div>
          <el-button size="small" @click="addSupply">补充到货批次</el-button>
          <div v-for="d in config.additional_supplies" :key="d.id" class="manual-supply"><el-select v-model="d.material_id" placeholder="外购件" size="small"><el-option v-for="p in config.purchased.filter(p => p.enabled)" :key="p.material_id" :value="p.material_id" :label="p.name" /></el-select><el-input-number v-model="d.quantity" :min="0.001" size="small" controls-position="right" /><input type="datetime-local" class="date-input" :value="localTime(d.available_at)" @input="d.available_at = parseLocal($event.target.value)" /><el-button link type="danger" @click="config.additional_supplies = config.additional_supplies.filter(s => s.id !== d.id)">删除</el-button></div>
        </el-collapse-item></el-collapse>
        <div class="chain-grid spaced"><el-form label-position="top"><el-form-item label="生产部件转运交接（分钟/整批，0表示无需独立作业）"><el-input-number v-model="config.transfer_minutes" :min="0" /></el-form-item><el-form-item label="成品转运交接（分钟/整批，原组装已含检测打包）"><el-input-number v-model="config.post_minutes" :min="0" /></el-form-item><el-form-item v-if="config.delivery_mode === 'saved'" label="出库装车（分钟/整批）"><el-input-number v-model="config.loading_minutes" :min="0.001" /></el-form-item><p class="hint">启用的交接作业各占1个作业位，故障、工时调整与其他任务一样可操作。</p></el-form>
          <el-form label-position="top"><el-form-item label="确认本批资源日历"><el-radio-group v-model="config.calendar.mode"><el-radio value="continuous">24小时连续</el-radio><el-radio value="shift">每日班次</el-radio></el-radio-group></el-form-item><el-form-item label="覆盖天数"><el-input-number v-model="config.calendar.days" :min="1" :max="28" /></el-form-item><template v-if="config.calendar.mode === 'shift'"><el-form-item label="每日开始 / 结束小时（北京时间）"><el-input-number v-model="config.calendar.begin_hour" :min="0" :max="23" /><el-input-number v-model="config.calendar.end_hour" :min="1" :max="24" /></el-form-item></template><p class="hint">日历必须容纳原生产甘特，否则预览提示冲突；不会悄悄重排原生产结果。</p></el-form></div>
      </el-tab-pane>
      <el-tab-pane label="3 时间与预览" name="preview">
        <template v-if="preview">
          <el-alert :title="preview.summary.delivery_bound ? '全链路校验通过，可明确启用为新运行' : '生产与组装已衔接；配送仍待绑定，不代表全链路交付计划'" :type="preview.summary.delivery_bound ? 'success' : 'warning'" :closable="false" show-icon />
          <div class="summary">{{ preview.plan.tasks.length }}项任务 · {{ preview.summary.units }}台组装 · {{ preview.summary.supplemental_tasks.length }}项转运交接 · {{ preview.summary.assembly_changes.length }}项原组装时间调整</div>
          <el-table :data="preview.time_mapping" size="small"><el-table-column label="环节" width="90"><template #default="{row}">{{ names[row.module] }}</template></el-table-column><el-table-column label="时间原点" width="160"><template #default="{row}">{{ formatTime(row.origin_at) }}</template></el-table-column><el-table-column prop="rule" label="映射规则" /></el-table>
          <el-collapse><el-collapse-item v-if="preview.summary.assembly_changes.length" title="核对原组装甘特的调整"><el-table :data="preview.summary.assembly_changes" size="small" max-height="220"><el-table-column prop="name" label="任务" /><el-table-column label="原开始"><template #default="{row}">{{ formatTime(row.original_start_at) }}</template></el-table-column><el-table-column label="衔接后开始"><template #default="{row}">{{ formatTime(row.start_at) }}</template></el-table-column></el-table></el-collapse-item><el-collapse-item title="查看各任务具体安排"><el-table :data="previewRows" size="small" max-height="300"><el-table-column prop="name" label="任务" min-width="190" /><el-table-column prop="resource" label="资源" min-width="150" /><el-table-column label="开始"><template #default="{row}">{{ formatTime(row.start_at) }}</template></el-table-column><el-table-column label="结束"><template #default="{row}">{{ formatTime(row.end_at) }}</template></el-table-column></el-table></el-collapse-item></el-collapse>
          <p class="hint">{{ preview.summary.note }}。客户窗口和发车日期不会随上游延期平移。没有客户承诺时仍显示交期待确认。</p>
        </template><el-empty v-else description="核对前两步，再点击“预览衔接”" :image-size="70" />
      </el-tab-pane>
    </el-tabs>
    <template #footer><div class="footer"><el-checkbox v-model="config.confirmed">已核对数量、用量、日历和交接参数</el-checkbox><span><el-button :loading="saving" @click="save">保存配置</el-button><el-button :loading="working" :disabled="!config.confirmed" @click="check">预览衔接</el-button><el-button type="primary" :loading="store.busy" :disabled="!preview?.can_activate" @click="activate">{{ store.instance ? '归档当前运行并启用' : '启用执行计划' }}</el-button></span></div></template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../../api/client'
import { useOperationsStore } from '../../stores/useOperationsStore'
const opened = defineModel({ type: Boolean })
const store = useOperationsStore(), root = '/api/operations-tools/plans/chain'
const tab = ref('sources'), error = ref(''), working = ref(false), saving = ref(false), reading = ref(false), preview = ref(null)
const productions = ref([]), catalog = ref({ processes: [], assembly: {}, routes: [], supply: { state: {} } }), route = ref(null)
const names = { production: '生产', assembly: '组装', logistics: '配送' }
const config = reactive({ name: '产业链执行计划', production: { plan_id: '', solver_id: '', time_unit: 'hours' }, start_at: '', units: 1,
  assembly_mode: 'supplement', assembly_id: '', assembly_origin_at: '', assembly_time_unit: 'minutes', delivery_mode: 'unbound',
  route_id: '', delivery_date: '', vehicle_capacity: null, customer_windows_hard: false, parts: [], purchased: [],
  stock_overrides: {}, arrival_overrides: {}, additional_supplies: [], customer_commitments: {}, transfer_minutes: 0, post_minutes: 0, loading_minutes: null,
  calendar: { mode: 'continuous', days: 7, begin_hour: 8, end_hour: 20 }, confirmed: false })
const localTime = value => value ? new Date((typeof value === 'number' ? value * 1000 : new Date(value).getTime()) + 8 * 3600000).toISOString().slice(0, 16) : ''
const parseLocal = value => value ? new Date(`${value}+08:00`).toISOString() : ''
const startLocal = computed({ get: () => localTime(config.start_at), set: v => { config.start_at = parseLocal(v) } })
const assemblyLocal = computed({ get: () => localTime(config.assembly_origin_at), set: v => { config.assembly_origin_at = parseLocal(v) } })
const formatTime = value => value == null ? '按齐套与资源计算' : new Date(value * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
const selectedProduction = computed(() => productions.value.find(p => p.id === config.production.plan_id))
const pendingDeliveries = computed(() => (catalog.value.supply?.state?.deliveries || []).filter(d => ['planned', 'on_the_way'].includes(d.status)))
const routeQuantity = computed(() => route.value?.customers.reduce((s, c) => s + Number(c.demand), 0) || 0)
const routeWindow = c => { if (!config.delivery_date) return '先选择配送日期'; const origin = new Date(`${config.delivery_date}T08:00:00+08:00`).getTime() / 1000; return `${formatTime(origin + Number(c.tw_start) * 60)}—${formatTime(origin + Number(c.tw_end) * 60)}` }
function addSupply() { config.additional_supplies.push({ id: crypto.randomUUID(), name: '运维补充到货', material_id: '', quantity: null, available_at: '' }) }
const previewRows = computed(() => preview.value?.plan.schedule.map(s => ({ ...s, name: preview.value.plan.tasks.find(t => t.id === s.task_id)?.name,
  resource: preview.value.plan.resources.find(r => r.id === s.resource_id)?.name })).sort((a,b) => a.start_at - b.start_at) || [])
function fail(e) { error.value = String(e.response?.data?.detail || e.message || e) }
watch(config, () => { preview.value = null; error.value = '' }, { deep: true, flush: 'sync' })
function selectProduction() { config.production.solver_id = selectedProduction.value?.solvers.includes(selectedProduction.value?.recommended_solver) ? selectedProduction.value.recommended_solver : selectedProduction.value?.solvers[0] || ''; config.parts = []; config.confirmed = false }
async function readProduction() { reading.value = true; try { const result = (await api.post(`${root}/production`, { ...config.production, start_at: config.start_at })).data; config.parts = result.orders.map(o => ({ order_id: o.id, name: o.name, enabled: true, material_id: `self:${o.id}`, produced_quantity: o.quantity_unit === '件' ? o.quantity : null, per_unit: 1, process_id: 0 })); config.confirmed = false; tab.value = 'binding' } catch(e) { fail(e) } finally { reading.value = false } }
async function readRoute() { try { route.value = (await api.get(`${root}/route`, { params: { route_id: config.route_id } })).data } catch(e) { route.value = null; fail(e) } }
watch(opened, async open => {
  if (!open) return
  error.value = ''; tab.value = 'sources'; preview.value = null
  try {
    const [sources, saved, prod] = await Promise.all([api.get(`${root}/sources`), api.get(`${root}/draft`), api.get('/api/operations-tools/plans/sources')])
    catalog.value = sources.data; productions.value = prod.data.plans
    if (saved.data.config) Object.assign(config, saved.data.config)
    else {
      config.purchased = catalog.value.supply.catalog.map(p => ({ material_id: p.id, name: p.name, enabled: true, per_unit: 1,
        process_id: catalog.value.processes.find(d => d.name === p.workstation)?.id ?? 8 }))
      config.stock_overrides = Object.fromEntries(catalog.value.supply.catalog.map(p => [p.id, catalog.value.supply.state.materials?.[p.id]?.on_hand ?? 0]))
      if (store.productionSource?.plan_id) { config.production.plan_id = store.productionSource.plan_id; selectProduction(); config.production.solver_id = store.productionSource.solver_id; config.production.time_unit = store.productionSource.time_unit || 'hours' }
    }
    // A reopened draft never silently reanchors an existing preview; the operator confirms a new calendar date.
    if (!config.start_at) config.start_at = new Date(Date.now() + 15 * 60000).toISOString()
    if (!config.delivery_date) config.delivery_date = localTime(config.start_at).slice(0, 10)
    for (const d of pendingDeliveries.value) if (!config.arrival_overrides[d.id] && catalog.value.supply.state.updated_at) config.arrival_overrides[d.id] = new Date(new Date(catalog.value.supply.state.updated_at).getTime() + Number(d.eta_minutes || 0) * 60000).toISOString()
    config.confirmed = false
    if (config.route_id) await readRoute()
  } catch(e) { fail(e) }
})
async function save() { saving.value = true; try { await api.put(`${root}/draft`, config); ElMessage.success('衔接配置已保存') } catch(e) { fail(e) } finally { saving.value = false } }
async function check() { working.value = true; error.value = ''; const snapshot = JSON.stringify(config); try { const result = (await api.post(`${root}/preview`, JSON.parse(snapshot))).data; if (snapshot !== JSON.stringify(config)) { error.value = '配置已变化，请重新预览'; return } preview.value = result; tab.value = 'preview' } catch(e) { fail(e) } finally { working.value = false } }
async function activate() {
  try {
    await ElMessageBox.confirm(store.instance ? '当前实例的进度和事件将完整归档。新执行计划按本次预览的固定日期启用，不继承旧MES或旧实例进度。' : '按预览的固定日期启用计划执行模拟？', '启用衔接计划', { confirmButtonText: '确认启用', cancelButtonText: '返回' })
    const result = await store.activate({ source: 'chain', preview_id: preview.value.preview_id, confirm_new_run: !!store.instance, previous_run_id: preview.value.previous_run_id })
    if (result.status === 'done') { opened.value = false; ElMessage.success('衔接计划已启用') } else ElMessage.info('启用提交中，请在运行记录中确认')
  } catch(e) { if (e !== 'cancel' && e !== 'close') fail(e) }
}
</script>

<style scoped>
.customer-commitment{display:flex;gap:12px;align-items:center;margin:10px 0;font-size:11px;line-height:1.6}.customer-commitment>span{flex:1}.customer-commitment input{max-width:190px}.manual-supply{display:grid;grid-template-columns:minmax(120px,1fr) 120px minmax(180px,1fr) 45px;gap:10px;align-items:center;margin:10px 0}@media(max-width:720px){.manual-supply{grid-template-columns:1fr 1fr}.customer-commitment{flex-wrap:wrap}}
.chain-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.full{width:100%}.hint{font-size:12px;color:#7e8fa5;line-height:1.7}.date-input{box-sizing:border-box;width:100%;height:33px;border:1px solid #dce3ed;border-radius:5px;padding:4px 9px;color:#566d8e;font:inherit;font-size:12px}.spaced{margin-top:18px}.extras{margin-top:14px}.arrival{display:flex;gap:15px;align-items:center;margin:10px 0;font-size:12px}.arrival input{max-width:240px}.footer{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}.summary{padding:17px 0;color:#567497;font-size:13px}:deep(.el-input-number){width:120px;max-width:100%}:deep(.el-form-item__label){font-size:12px}@media(max-width:720px){.chain-grid{grid-template-columns:1fr;gap:8px}.arrival{flex-direction:column;align-items:stretch}.footer>span{display:flex;flex-wrap:wrap;gap:5px}}
</style>
