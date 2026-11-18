<template>
  <el-dialog v-model="opened" title="计划配置" :width="setupMode === 'quick' ? 'min(720px, 96vw)' : 'min(1050px, 96vw)'" :close-on-click-modal="false">
    <el-radio-group v-model="setupMode" class="setup-mode"><el-radio-button value="full">完整衔接</el-radio-button><el-radio-button value="quick">快捷使用</el-radio-button></el-radio-group>
    <QuickPlanSetup v-if="setupMode === 'quick'" :plans="productions" @close="opened = false" />
    <template v-else>
    <div class="case-actions"><el-select v-model="baselineId" style="width:235px" aria-label="示范基线案例"><el-option v-for="item in baselines" :key="item.id" :value="item.id" :label="item.name" :disabled="!item.ready" /></el-select><el-button :loading="loadingBaseline" @click="loadBaseline">载入案例</el-button><el-button @click="newFromModules">从模块结果新建</el-button><el-button :disabled="!config.start_at" :loading="rebasing" @click="rebaseDraft">整体映射到当前时间</el-button><span v-if="config.baseline_case" class="hint">{{ config.production_sources.length || 1 }}家工厂 · 外购与运输 · {{ config.units }}台交付</span></div>
    <el-collapse v-if="config.case_assumptions?.length"><el-collapse-item title="案例来源与已声明参数"><p v-for="note in config.case_assumptions" :key="note" class="hint">{{note}}</p></el-collapse-item></el-collapse>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon /><el-table v-if="conflicts.length" :data="conflicts" size="small" max-height="180"><el-table-column prop="target" label="冲突对象" width="180" /><el-table-column prop="message" label="业务衔接冲突" /></el-table>
    <el-tabs v-model="tab">
      <el-tab-pane label="1 计划来源" name="sources">
        <div class="chain-grid">
          <el-form label-position="top">
            <el-form-item label="计划名称"><el-input v-model="config.name" /></el-form-item>
            <el-form-item label="生产计划"><el-select v-model="config.production.plan_id" filterable class="full" @change="switchSingleProduction"><el-option v-for="p in productions" :key="p.id" :value="p.id" :label="p.name" /></el-select></el-form-item>
            <el-collapse><el-collapse-item title="排程与时间单位"><div class="chain-grid"><el-form-item label="排程结果"><el-select v-model="config.production.solver_id" class="full"><el-option v-for="s in selectedProduction?.solvers || []" :key="s" :value="s" :label="s.toUpperCase()" /></el-select></el-form-item><el-form-item label="原生产时间单位"><el-select v-model="config.production.time_unit" class="full"><el-option value="hours" label="小时" /><el-option value="minutes" label="分钟" /><el-option value="seconds" label="秒" /></el-select></el-form-item></div></el-collapse-item></el-collapse>
            <el-form-item label="执行起点（北京时间）"><input v-model="startLocal" type="datetime-local" class="date-input" /></el-form-item>
            <el-collapse><el-collapse-item title="多个工厂"><el-button size="small" @click="config.production_sources.push({factory_id:'',plan_id:'',solver_id:'',time_unit:'hours',origin_offset_hours:0,source_zero_offset_hours:0})">增加工厂来源</el-button><div v-for="(s,index) in config.production_sources" :key="index" class="factory-source"><div class="multi-source"><el-input v-model="s.factory_id" placeholder="工厂标识" /><el-select v-model="s.plan_id" placeholder="保存计划" @change="s.job_indices = undefined; s.job_names = []"><el-option v-for="p in productions" :key="p.id" :value="p.id" :label="p.name" /></el-select><el-select v-model="s.solver_id" placeholder="算法"><el-option v-for="a in productions.find(p=>p.id===s.plan_id)?.solvers || []" :key="a" :value="a" :label="a.toUpperCase()" /></el-select><el-select v-model="s.time_unit"><el-option value="hours" label="小时" /><el-option value="minutes" label="分钟" /><el-option value="seconds" label="秒" /></el-select><el-button link type="danger" @click="config.production_sources.splice(index,1)">移除</el-button></div><div class="factory-scope"><el-select v-model="s.job_indices" @change="s.job_names = (productions.find(p=>p.id===s.plan_id)?.jobs || []).filter(j=>s.job_indices?.includes(j.index)).map(j=>j.name); if (!s.job_indices?.length) s.job_indices = undefined" multiple collapse-tags collapse-tags-tooltip placeholder="全部工单（可选范围）" aria-label="工厂工单范围"><el-option v-for="j in productions.find(p=>p.id===s.plan_id)?.jobs || []" :key="j.index" :value="j.index" :label="j.name" /></el-select><label>源甘特零点（小时）<el-input-number v-model="s.source_zero_offset_hours" :min="0" :max="672" controls-position="right" /></label></div></div><p class="hint">按选定工单划分工厂；机器ID保持原样，共用设备不能重复归属。</p></el-collapse-item></el-collapse>

          </el-form>
          <el-form label-position="top">
            <el-form-item label="组装数量（台）"><el-input-number v-model="config.units" :min="1" :max="100" :precision="0" /></el-form-item>
            <el-form-item label="组装来源"><el-radio-group v-model="config.assembly_mode"><el-radio value="supplement">按原工艺补排</el-radio><el-radio value="saved" :disabled="!compatibleAssembly.length">已保存组装结果</el-radio></el-radio-group></el-form-item>
            <template v-if="config.assembly_mode === 'saved'"><el-form-item label="组装计划（自动带入批量）"><el-select v-model="config.assembly_id" class="full" @change="selectAssembly"><el-option v-for="r in compatibleAssembly" :key="r.id" :value="r.id" :label="r.name" /></el-select></el-form-item><el-form-item label="组装时间起点（北京时间）"><input v-model="assemblyLocal" type="datetime-local" class="date-input" /></el-form-item><el-form-item label="时间单位"><el-select v-model="config.assembly_time_unit" class="full"><el-option value="minutes" label="分钟" /><el-option value="seconds" label="秒" /><el-option value="hours" label="小时" /></el-select></el-form-item></template>
            <p v-else class="hint">复用原9工序、18工位，按齐套时间排程。</p>
            <p v-if="catalog.assembly?.results?.length" class="hint">组装结果 {{ compatibleAssembly.length }} 份可用<template v-if="!compatibleAssembly.length">，当前可用原工艺排程。</template></p>
            <el-collapse v-if="incompatibleAssembly.length"><el-collapse-item title="查看不可用原因"><el-table :data="incompatibleAssembly" size="small" max-height="190"><el-table-column prop="name" label="结果" width="180" /><el-table-column prop="reason" label="原因" /></el-table></el-collapse-item></el-collapse>
            <p v-if="catalog.assembly?.messages?.length" class="hint">{{ catalog.assembly.messages[0] }}</p>
            <el-form-item label="配送来源"><el-radio-group v-model="config.delivery_mode"><el-radio value="saved">已保存车辆路线</el-radio><el-radio value="unbound">暂不绑定</el-radio></el-radio-group></el-form-item>
            <template v-if="config.delivery_mode === 'saved'"><el-form-item label="配送历史结果"><el-select v-model="config.source_dataset" class="full" clearable placeholder="当前模块结果" @change="selectDeliveryRecord"><el-option value="" label="当前模块最新结果" /><el-option v-for="r in deliveryRecords" :key="r.id" :value="`record:${r.id}`" :label="r.name" /><el-option v-if="config.source_dataset && !config.source_dataset.startsWith('record:')" :value="config.source_dataset" label="当前案例数据" /></el-select></el-form-item><el-select v-model="config.route_id" filterable class="full" placeholder="选择本批配送路线" @change="readRoute"><el-option v-for="r in catalog.routes || []" :key="r.id" :value="r.id" :label="r.name" /></el-select><p v-if="route" class="hint">原客户：{{ route.customers.map(c => `${c.cust_name || c.cust_id} ${c.demand}件`).join('；') }}。合计 {{ routeQuantity }} 件，须与组装数量一致。<br />发车 {{ formatTime(dispatchAt) }}（原点 {{ formatTime(deliveryOrigin) }}＋路线偏移）。</p><div class="chain-grid"><el-form-item label="配送日期（修改后以08:00为零点）"><input v-model="config.delivery_date" type="date" class="date-input" @change="config.delivery_origin_at = undefined" /></el-form-item><el-form-item label="车辆容量（件）"><el-input-number v-model="config.vehicle_capacity" :min="1" /></el-form-item></div><el-checkbox v-model="config.customer_windows_hard">严格遵守收货窗口</el-checkbox><el-collapse v-if="route"><el-collapse-item title="客户窗口与交期"><div v-for="c in route.customers" :key="c.cust_id" class="customer-commitment"><span>{{ c.cust_name || c.cust_id }} · {{ c.demand }}件<br />窗口 {{ routeWindow(c) }}</span><input type="datetime-local" class="date-input" :value="localTime(config.customer_commitments[String(Number(c.cust_id))])" @input="config.customer_commitments[String(Number(c.cust_id))] = parseLocal($event.target.value)" /></div><p class="hint">交期可留空，留空则待确认。</p></el-collapse-item></el-collapse></template>
          </el-form>
        </div>
      </el-tab-pane>
      <el-tab-pane label="2 部件用量" name="binding">
        <p class="hint">选择部件，核对产出数量与每台用量。</p>
        <el-table :data="config.parts" size="small" max-height="260" empty-text="先在第1步读取生产工单">
          <el-table-column label="采用" width="58"><template #default="{row}"><el-checkbox v-model="row.enabled" /></template></el-table-column>
          <el-table-column prop="name" label="自制部件" min-width="170" />
          <el-table-column label="整批产出件数" width="145"><template #default="{row}"><el-input-number v-model="row.produced_quantity" :min="0.001" size="small" controls-position="right" /></template></el-table-column>
          <el-table-column label="每台用量" width="135"><template #default="{row}"><el-input-number v-model="row.per_unit" :min="0.001" size="small" controls-position="right" /></template></el-table-column>
          <el-table-column label="消耗工序" width="145"><template #default="{row}"><el-select v-model="row.process_id" size="small"><el-option v-for="p in catalog.processes" :key="p.id" :value="p.id" :label="p.name" /></el-select></template></el-table-column>
        </el-table>
        <el-collapse class="extras"><el-collapse-item title="外购件与到货" name="materials">
          <el-table :data="config.purchased" size="small" max-height="290">
            <el-table-column label="采用" width="58"><template #default="{row}"><el-checkbox v-model="row.enabled" /></template></el-table-column><el-table-column prop="name" label="外购件" min-width="130" />
            <el-table-column label="每台用量" width="145"><template #default="{row}"><el-input-number v-model="row.per_unit" :min="0.001" size="small" controls-position="right" /></template></el-table-column>
            <el-table-column label="可用库存" width="145"><template #default="{row}"><el-input-number v-model="config.stock_overrides[row.material_id]" :min="0" size="small" controls-position="right" /></template></el-table-column>
            <el-table-column label="消耗工序" width="145"><template #default="{row}"><el-select v-model="row.process_id" size="small"><el-option v-for="p in catalog.processes" :key="p.id" :value="p.id" :label="p.name" /></el-select></template></el-table-column>
          </el-table>
          <p class="hint">库存来自供给快照；默认用量需核对。</p>
          <div v-for="d in pendingDeliveries" :key="d.id" class="arrival"><span>{{ d.supplier_name }} · {{ d.material_id }} · {{ d.quantity }}件</span><input type="datetime-local" class="date-input" :value="localTime(config.arrival_overrides[d.id])" @input="config.arrival_overrides[d.id] = parseLocal($event.target.value)" /></div>
          <el-button size="small" @click="addSupply">补充到货批次</el-button>
          <div v-for="d in config.additional_supplies" :key="d.id" class="manual-supply"><el-select v-model="d.material_id" placeholder="外购件" size="small"><el-option v-for="p in config.purchased.filter(p => p.enabled)" :key="p.material_id" :value="p.material_id" :label="p.name" /></el-select><el-input-number v-model="d.quantity" :min="0.001" size="small" controls-position="right" /><input type="datetime-local" class="date-input" :value="localTime(d.available_at)" @input="d.available_at = parseLocal($event.target.value)" /><el-button link type="danger" @click="config.additional_supplies = config.additional_supplies.filter(s => s.id !== d.id)">删除</el-button></div>
        </el-collapse-item></el-collapse>
        <el-collapse class="spaced"><el-collapse-item title="交接与班次设置"><div class="chain-grid spaced"><el-form label-position="top"><el-form-item label="部件交接（分钟/批）"><el-input-number v-model="config.transfer_minutes" :min="0" /></el-form-item><el-form-item label="成品交接（分钟/批）"><el-input-number v-model="config.post_minutes" :min="0" /></el-form-item><el-form-item v-if="config.delivery_mode === 'saved'" label="出库装车（分钟/批）"><el-input-number v-model="config.loading_minutes" :min="0.001" /></el-form-item><p class="hint">交接时间填0则不单独安排作业。</p></el-form>
          <el-form label-position="top"><el-form-item label="工作日历"><el-radio-group v-model="config.calendar.mode"><el-radio value="continuous">24小时连续</el-radio><el-radio value="shift">每日班次</el-radio></el-radio-group></el-form-item><el-form-item label="覆盖天数"><el-input-number v-model="config.calendar.days" :min="1" :max="28" /></el-form-item><template v-if="config.calendar.mode === 'shift'"><el-form-item label="班次起止（北京时间/小时）"><el-input-number v-model="config.calendar.begin_hour" :min="0" :max="23" /><el-input-number v-model="config.calendar.end_hour" :min="1" :max="24" /></el-form-item></template><p class="hint">日历需覆盖原生产排程。</p></el-form></div></el-collapse-item></el-collapse>
      </el-tab-pane>
      <el-tab-pane label="3 供给运输" name="coherence"><CoherenceEditor :config="config" :catalog="catalog" :route="route" /></el-tab-pane>
      <el-tab-pane label="4 确认启用" name="preview">
        <template v-if="preview">
          <el-alert :title="preview.summary.delivery_bound ? '全链路校验通过' : '生产、组装已衔接；配送未绑定'" :type="preview.summary.delivery_bound ? 'success' : 'warning'" :closable="false" show-icon />
          <el-alert v-if="preview.summary.business_validation?.manual_mappings?.length" :title="`${preview.summary.business_validation.manual_mappings.length}项来源使用人工映射，请核对。`" type="warning" :closable="false" />
          <el-collapse><el-collapse-item title="供需校验详情"><p class="hint">{{preview.summary.business_validation?.product_id}} · BOM {{preview.summary.business_validation?.bom_revision}} · 组装地点 {{preview.summary.business_validation?.assembly_site}}</p><el-table :data="preview.summary.business_validation?.checks || []" size="small" max-height="220"><el-table-column prop="target" label="核验对象" width="220" /><el-table-column prop="message" label="已满足的约束" /></el-table><el-table v-if="preview.summary.business_validation?.manual_mappings?.length" :data="preview.summary.business_validation.manual_mappings" size="small" max-height="180"><el-table-column prop="target" label="人工映射对象" width="220" /><el-table-column prop="note" label="原数据缺项说明" /></el-table></el-collapse-item></el-collapse>
          <div class="handoff-times"><div v-for="point in handoffPoints" :key="point.label"><span>{{ point.label }}</span><b>{{ point.at == null ? '未绑定' : formatTime(point.at) }}</b></div></div>
          <p class="hint">各环节统一北京时间。组装完成后装车，固定发车与客户窗口不自动后移。</p>
          <div class="summary">{{ preview.plan.tasks.length }}项任务 · {{ preview.summary.units }}台组装 · {{ preview.summary.supplemental_tasks.length }}项转运交接 · {{ preview.summary.assembly_changes.length }}项原组装时间调整</div>
          <el-collapse><el-collapse-item title="时间映射"><el-table :data="preview.time_mapping" size="small"><el-table-column label="环节" width="90"><template #default="{row}">{{ names[row.module] }}</template></el-table-column><el-table-column label="时间原点" width="160"><template #default="{row}">{{ formatTime(row.origin_at) }}</template></el-table-column><el-table-column prop="rule" label="映射规则" /></el-table></el-collapse-item></el-collapse>
          <el-collapse><el-collapse-item v-if="preview.summary.assembly_changes.length" title="组装时间变化"><el-table :data="preview.summary.assembly_changes" size="small" max-height="220"><el-table-column prop="name" label="任务" /><el-table-column label="原开始"><template #default="{row}">{{ formatTime(row.original_start_at) }}</template></el-table-column><el-table-column label="衔接后开始"><template #default="{row}">{{ formatTime(row.start_at) }}</template></el-table-column></el-table></el-collapse-item><el-collapse-item title="任务安排"><el-table :data="previewRows" size="small" max-height="300"><el-table-column prop="name" label="任务" min-width="190" /><el-table-column prop="resource" label="资源" min-width="150" /><el-table-column label="开始"><template #default="{row}">{{ formatTime(row.start_at) }}</template></el-table-column><el-table-column label="结束"><template #default="{row}">{{ formatTime(row.end_at) }}</template></el-table-column></el-table></el-collapse-item></el-collapse>
          <el-collapse v-if="preview.summary.time_validation"><el-collapse-item :title="`时间衔接校验 · ${preview.summary.time_validation.checks.length} 项通过`"><el-table :data="preview.summary.time_validation.checks" size="small" max-height="230"><el-table-column prop="target" label="对象" min-width="180" /><el-table-column prop="message" label="校验" /></el-table></el-collapse-item></el-collapse>
          <p class="hint">客户窗口与发车日期保持原约定；交期缺失则待确认。</p>
        </template><el-empty v-else description="完成供给运输配置后，校验并预览" :image-size="70" />
      </el-tab-pane>
    </el-tabs>
    </template>
    <template v-if="setupMode === 'full'" #footer><div class="footer">
      <el-button link :loading="saving" @click="save">保存草稿</el-button>
      <div class="footer-actions">
        <el-checkbox v-if="tab === 'coherence'" v-model="config.confirmed">已核对配置</el-checkbox>
        <el-button v-if="tab !== 'sources'" @click="previousStep">上一步</el-button>
        <el-button v-if="tab === 'sources'" type="primary" :loading="reading" :disabled="(!config.production.plan_id && !config.production_sources.length) || !config.production.solver_id && !config.production_sources.length" @click="nextSources">下一步</el-button>
        <el-button v-else-if="tab === 'binding'" type="primary" @click="tab = 'coherence'">下一步</el-button>
        <el-button v-else-if="tab === 'coherence'" type="primary" :loading="working" :disabled="!config.confirmed" @click="check">校验并预览</el-button>
        <template v-else><el-button :loading="working" :disabled="!config.confirmed" @click="check">重新校验</el-button><el-button type="primary" :loading="store.busy" :disabled="!preview?.can_activate" @click="activate">启用计划</el-button></template>
      </div>
    </div></template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../../api/client'
import CoherenceEditor from './CoherenceEditor.vue'
import QuickPlanSetup from './QuickPlanSetup.vue'
import { chainHandoffs } from '../../utils/operationsPlan'
import { useOperationsStore } from '../../stores/useOperationsStore'
const opened = defineModel({ type: Boolean })
const props = defineProps({exampleCase:{type:String,default:''},historyRecord:{type:String,default:''},historyModule:{type:String,default:''}})
const deliveryRecords=ref([]), loadedHistoryRecord=ref('')
const baselines = ref([]), baselineId = ref('chain-demo-normal'), loadedRequestedCase = ref('')
const store = useOperationsStore(), root = '/api/operations-tools/plans/chain'
const conflicts = ref([]), setupMode = ref('full')
const lastReadSource = ref(''), loadingBaseline = ref(false), rebasing = ref(false)
const sourceSignature = computed(() => JSON.stringify([config.production, config.production_sources, config.start_at]))
function previousStep() { const steps = ['sources', 'binding', 'coherence', 'preview']; tab.value = steps[Math.max(0, steps.indexOf(tab.value) - 1)] }
function nextSources() { if (config.parts.length && lastReadSource.value === sourceSignature.value) tab.value = 'binding'; else return readProduction() }
const tab = ref('sources'), error = ref(''), working = ref(false), saving = ref(false), reading = ref(false), preview = ref(null)
const productions = ref([]), catalog = ref({ processes: [], assembly: {}, routes: [], supply: { state: {} } }), route = ref(null)
const names = { production: '生产', assembly: '组装', logistics: '配送' }
const config = reactive({ coherence_version:1, production_sources:[], assembly_bom:{product_id:'',spec:'',uom:'台',revision:'v1',assembly_site:'',lines:[]}, procurement_orders:[], procurement_links:{}, inbound_shipments:[], dispatch_product_id:'', dispatch_spec:'', dispatch_uom:'台', dispatch_depot_id:'', name: '产业链执行计划', production: { plan_id: '', solver_id: '', time_unit: 'hours' }, start_at: '', units: 1,
  assembly_mode: 'supplement', assembly_id: '', assembly_origin_at: '', assembly_time_unit: 'minutes', delivery_mode: 'unbound',
  route_id: '', delivery_date: '', vehicle_capacity: null, customer_windows_hard: false, parts: [], purchased: [],
  stock_overrides: {}, arrival_overrides: {}, additional_supplies: [], customer_commitments: {}, transfer_minutes: 0, post_minutes: 0, loading_minutes: null,
  calendar: { mode: 'continuous', days: 7, begin_hour: 8, end_hour: 20 }, confirmed: false })
const initialConfig = JSON.parse(JSON.stringify(config))
function fillSupplyDefaults() {
  config.purchased = (catalog.value.supply.catalog || []).map(p => ({material_id:p.id,name:p.name,enabled:true,per_unit:1,supplier_id:p.supplier_id || p.supplier || '',mapping_confirmed:false,process_id:catalog.value.processes.find(d=>d.name===p.workstation)?.id ?? 8}))
  config.stock_overrides = Object.fromEntries((catalog.value.supply.catalog || []).map(p => [p.id,catalog.value.supply.state.materials?.[p.id]?.on_hand ?? 0]))
}
async function newFromModules() {
  for (const key of Object.keys(config)) if (!(key in initialConfig)) delete config[key]
  Object.assign(config, JSON.parse(JSON.stringify(initialConfig)))
  config.start_at = new Date(Date.now()+15*60000).toISOString()
  route.value = null; lastReadSource.value = ''; tab.value = 'sources'
  try { catalog.value = (await api.get(`${root}/sources`)).data; fillSupplyDefaults() } catch(e) { fail(e) }
}
function switchSingleProduction() { config.production_sources = []; config.baseline_case = ''; config.case_assumptions = []; selectProduction() }
const localTime = value => value ? new Date((typeof value === 'number' ? value * 1000 : new Date(value).getTime()) + 8 * 3600000).toISOString().slice(0, 16) : ''
const parseLocal = value => value ? new Date(`${value}+08:00`).toISOString() : ''
const startLocal = computed({ get: () => localTime(config.start_at), set: v => { config.start_at = parseLocal(v) } })
const assemblyLocal = computed({ get: () => localTime(config.assembly_origin_at), set: v => { config.assembly_origin_at = parseLocal(v) } })
const formatTime = value => value == null ? '按齐套与资源计算' : new Date(value * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
const selectedProduction = computed(() => productions.value.find(p => p.id === config.production.plan_id))
const compatibleAssembly = computed(() => (catalog.value.assembly?.results || []).filter(r => r.compatible === true))
const incompatibleAssembly = computed(() => (catalog.value.assembly?.results || []).filter(r => r.compatible !== true))
function selectAssembly() { const row = compatibleAssembly.value.find(r => r.id === config.assembly_id); if (row) { config.units = Number(row.units); if (!config.assembly_origin_at) config.assembly_origin_at = config.start_at } }
const pendingDeliveries = computed(() => (catalog.value.supply?.state?.deliveries || []).filter(d => ['planned', 'on_the_way'].includes(d.status)))
const deliveryOrigin = computed(() => config.delivery_origin_at != null ? (typeof config.delivery_origin_at === 'number' ? config.delivery_origin_at : new Date(config.delivery_origin_at).getTime() / 1000) : config.delivery_date ? new Date(`${config.delivery_date}T08:00:00+08:00`).getTime() / 1000 : null)
const dispatchAt = computed(() => deliveryOrigin.value != null && route.value ? deliveryOrigin.value + Number(route.value.route.start_time_min) * 60 : null)
const routeQuantity = computed(() => route.value?.customers.reduce((s, c) => s + Number(c.demand), 0) || 0)
const routeWindow = c => { if (!config.delivery_date) return '先选择配送日期'; const origin = deliveryOrigin.value; return `${formatTime(origin + Number(c.tw_start) * 60)}—${formatTime(origin + Number(c.tw_end) * 60)}` }
function addSupply() { config.additional_supplies.push({ id: crypto.randomUUID(), name: '运维补充到货', material_id: '', quantity: null, available_at: '' }) }
async function loadBaseline() {
  loadingBaseline.value = true; error.value = ''
  try {
    const result = (await api.post(`${root}/baseline`, {case_id:baselineId.value})).data
    Object.assign(config, result.config)
    catalog.value = (await api.get(`${root}/sources`, {params:{dataset:config.source_dataset || ''}})).data
    lastReadSource.value = sourceSignature.value; tab.value = 'sources'
    await readRoute(); ElMessage.success('完整案例已载入，可逐项查看、编辑并预览')
  } catch(e) { fail(e) } finally { loadingBaseline.value = false }
}
async function rebaseDraft() {
  rebasing.value = true
  try { Object.assign(config, (await api.post(`${root}/rebase`, {config:JSON.parse(JSON.stringify(config))})).data.config); lastReadSource.value = sourceSignature.value; ElMessage.success('所有案例时刻已整体平移，请重新预览') } catch(e) { fail(e) } finally { rebasing.value = false }
}
const handoffPoints = computed(() => chainHandoffs(preview.value?.plan))
const previewRows = computed(() => preview.value?.plan.schedule.map(s => ({ ...s, name: preview.value.plan.tasks.find(t => t.id === s.task_id)?.name,
  resource: preview.value.plan.resources.find(r => r.id === s.resource_id)?.name })).sort((a,b) => a.start_at - b.start_at) || [])
function fail(e) { error.value = String(e.response?.data?.detail || e.message || e); conflicts.value = e.response?.data?.coherence?.conflicts || [] }
watch(config, () => { preview.value = null; error.value = ''; conflicts.value = [] }, { deep: true, flush: 'sync' })
function selectProduction() { const solver = selectedProduction.value?.solvers.includes(selectedProduction.value?.recommended_solver) ? selectedProduction.value.recommended_solver : selectedProduction.value?.solvers[0] || ''; config.production = {plan_id:config.production.plan_id,solver_id:solver,time_unit:config.production.time_unit || 'hours'}; config.parts = []; config.confirmed = false }
watch(() => config.production_sources.length, (count, old) => { if (!count && old) selectProduction() })
async function readProduction() {
  reading.value = true
  const signature = sourceSignature.value
  const body = JSON.parse(JSON.stringify({ ...config.production, production_sources: config.production_sources, start_at: config.start_at }))
  try {
    const result = (await api.post(`${root}/production`, body)).data
    if (signature !== sourceSignature.value) { error.value = '计划来源已变化，请重新读取'; return }
    config.parts = result.orders.map(o => ({ order_id: o.id, name: o.name, enabled: true, material_id: `self:${o.id}`, produced_quantity: o.quantity_unit === '件' ? o.quantity : null, per_unit: 1, process_id: 0, factory_id: o.business_source?.factory_id || '', business_source:o.business_source || {}, mapping_confirmed:false }))
    config.confirmed = false
    lastReadSource.value = signature
    tab.value = 'binding'
  } catch(e) { fail(e) } finally { reading.value = false }
}
async function selectDeliveryRecord(){try{catalog.value=(await api.get(`${root}/sources`,{params:{dataset:config.source_dataset||''}})).data;config.route_id=catalog.value.routes[0]?.id||'';config.confirmed=false;if(config.route_id)await readRoute();else route.value=null}catch(e){fail(e)}}
async function loadHistoryRecord(){
  const key=props.historyRecord,module=props.historyModule
  if(!key || !['production','assembly','delivery'].includes(module))return
  const base=`/api/operations-tools/data-center/${module}/${encodeURIComponent(key)}`
  const record=(await api.get(base)).data
  if(record.payload.chain_config){
    const result=(await api.post(`${base}/prepare`,{})).data
    for(const field of Object.keys(config))if(!(field in initialConfig))delete config[field]
    Object.assign(config,result.config)
    catalog.value=(await api.get(`${root}/sources`,{params:{dataset:config.source_dataset||''}})).data
    lastReadSource.value=sourceSignature.value;tab.value='sources';await readRoute()
  }else{
    await newFromModules()
    if(module==='assembly'){if(!record.compatible)throw Error('该历史结果与当前工艺不兼容，请先在组装模块适配');config.assembly_mode='saved';config.assembly_id=`history:${key}:${record.selected_episode || 1}`;config.units=record.units;config.assembly_origin_at=config.start_at}
    if(module==='delivery'){config.source_dataset=`record:${key}`;config.delivery_mode='saved';await selectDeliveryRecord()}
  }
  loadedHistoryRecord.value=`${module}:${key}`
}
async function readRoute() { try { route.value = (await api.get(`${root}/route`, { params: { route_id: config.route_id, dataset:config.source_dataset || '' } })).data } catch(e) { route.value = null; fail(e) } }
watch(opened, async open => {
  if (!open) return
  error.value = ''; tab.value = 'sources'; preview.value = null; setupMode.value = 'full'
  try {
    const [sources, saved, prod, examples, deliveries] = await Promise.all([api.get(`${root}/sources`), api.get(`${root}/draft`), api.get('/api/operations-tools/plans/sources'), api.get(`${root}/baselines`),api.get('/api/operations-tools/data-center/delivery')])
    deliveryRecords.value=deliveries.data.records
    baselines.value = examples.data.cases
    catalog.value = sources.data; productions.value = prod.data.plans
    if (saved.data.config) { Object.assign(config, saved.data.config); if (config.source_dataset) catalog.value = (await api.get(`${root}/sources`, {params:{dataset:config.source_dataset}})).data; lastReadSource.value = sourceSignature.value }
    else {
      fillSupplyDefaults()
      if (store.productionSource?.plan_id) { config.production.plan_id = store.productionSource.plan_id; selectProduction(); config.production.solver_id = store.productionSource.solver_id; config.production.time_unit = store.productionSource.time_unit || 'hours' }
    }
    // A reopened draft never silently reanchors an existing preview; the operator confirms a new calendar date.
    if (!config.start_at) config.start_at = new Date(Date.now() + 15 * 60000).toISOString()
    if (!config.delivery_date) config.delivery_date = localTime(config.start_at).slice(0, 10)
    for (const d of pendingDeliveries.value) if (!config.arrival_overrides[d.id] && catalog.value.supply.state.updated_at) config.arrival_overrides[d.id] = new Date(new Date(catalog.value.supply.state.updated_at).getTime() + Number(d.eta_minutes || 0) * 60000).toISOString()
    config.coherence_version = 1; config.confirmed = false
    if (config.route_id) await readRoute()
    if(props.historyRecord && loadedHistoryRecord.value!==`${props.historyModule}:${props.historyRecord}`) await loadHistoryRecord()
    else if (props.exampleCase && loadedRequestedCase.value !== props.exampleCase) { baselineId.value = props.exampleCase; await loadBaseline(); loadedRequestedCase.value = props.exampleCase }
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
.case-actions{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin:5px 0 15px}.case-actions :deep(.el-button+.el-button){margin-left:0}.factory-source{padding-bottom:10px}.factory-scope{display:flex;gap:12px;align-items:center}.factory-scope>.el-select{flex:1}.factory-scope label{font-size:11px;color:#7e8fa5;display:flex;align-items:center;gap:8px}.handoff-times{display:flex;gap:12px;flex-wrap:wrap;margin-top:20px}.handoff-times>div{flex:1;min-width:130px;padding:12px;background:#f5f8fc;border-radius:7px}.handoff-times span{display:block;font-size:12px;color:#8798ad;margin-bottom:8px}.handoff-times b{font-size:13px;font-weight:500;color:#567497}.setup-mode{margin-bottom:12px}.footer-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.footer-actions :deep(.el-button+.el-button){margin-left:0}.multi-source{display:grid;grid-template-columns:1fr 1.5fr .8fr .8fr 40px;gap:7px;margin:10px 0}
.customer-commitment{display:flex;gap:12px;align-items:center;margin:10px 0;font-size:11px;line-height:1.6}.customer-commitment>span{flex:1}.customer-commitment input{max-width:190px}.manual-supply{display:grid;grid-template-columns:minmax(120px,1fr) 120px minmax(180px,1fr) 45px;gap:10px;align-items:center;margin:10px 0}@media(max-width:720px){.manual-supply{grid-template-columns:1fr 1fr}.customer-commitment{flex-wrap:wrap}}
.chain-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.full{width:100%}.hint{font-size:12px;color:#7e8fa5;line-height:1.7}.date-input{box-sizing:border-box;width:100%;height:33px;border:1px solid #dce3ed;border-radius:5px;padding:4px 9px;color:#566d8e;font:inherit;font-size:12px}.spaced{margin-top:18px}.extras{margin-top:14px}.arrival{display:flex;gap:15px;align-items:center;margin:10px 0;font-size:12px}.arrival input{max-width:240px}.footer{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}.summary{padding:17px 0;color:#567497;font-size:13px}:deep(.el-input-number){width:120px;max-width:100%}:deep(.el-form-item__label){font-size:12px}@media(max-width:720px){.chain-grid{grid-template-columns:1fr;gap:8px}.arrival{flex-direction:column;align-items:stretch}.footer>span{display:flex;flex-wrap:wrap;gap:5px}}
</style>
