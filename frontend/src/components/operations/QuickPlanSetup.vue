<template>
  <div class="quick-setup">
    <div class="source-options">
      <button v-if="store.instance" :class="{ active: source === 'current' }" @click="source = 'current'"><b>沿用当前案例</b><span>保留各环节关联</span></button>
      <button :class="{ active: source === 'production' }" @click="source = 'production'"><b>接入生产计划</b><span>读取库内已保存排程</span></button>
    </div>
    <template v-if="source === 'current' && store.instance">
      <div class="case-card"><b>{{ store.instance.plan.name }}</b><div class="coverage"><el-tag v-for="(label, key) in stages" :key="key" :type="store.instance.plan.coverage?.[key] === 'bound' ? 'success' : 'info'" size="small">{{ label }} {{ store.instance.plan.coverage?.[key] === 'bound' ? '已接入' : '未接入' }}</el-tag></div><p>原案例从当前时间重开，本轮记录归档。</p></div>
      <div class="quick-footer"><el-button @click="$emit('close')">继续本轮</el-button><el-button type="primary" :loading="store.busy" @click="restart">重开此案例</el-button></div>
    </template>
    <template v-else>
      <el-form label-position="top">
        <el-form-item label="生产计划"><el-select v-model="planId" filterable class="full" placeholder="选择已保存计划"><el-option v-for="p in plans" :key="p.id" :value="p.id" :label="p.name" :disabled="!p.can_preview" /></el-select></el-form-item>
        <el-collapse><el-collapse-item title="排程与时间单位"><div class="settings"><el-select v-model="solver" aria-label="排程结果"><el-option v-for="s in selectedPlan?.solvers || []" :key="s" :value="s" :label="s.toUpperCase()" /></el-select><el-select v-model="unit" aria-label="生产时间单位"><el-option value="hours" label="小时（原系统）" /><el-option value="minutes" label="分钟" /><el-option value="seconds" label="秒" /></el-select></div></el-collapse-item></el-collapse>
      </el-form>
      <p class="hint">仅接入生产。需要组装、采购与配送时，选择“完整衔接”。</p>
      <div v-if="preview" class="preview-card"><b>{{ preview.can_activate ? '校验通过' : '需处理冲突' }}</b><span>{{ preview.plan.tasks.length }} 道工序 · {{ preview.plan.resources.length }} 台设备</span><p v-for="(v, i) in preview.validation?.violations?.slice(0, 3) || []" :key="i">{{ v.message }}</p></div>
      <div class="quick-footer"><el-button :loading="checking" :disabled="!planId || !solver" @click="check">预览校验</el-button><el-button type="primary" :loading="store.busy" :disabled="!preview?.can_activate || checking" @click="activate">启用生产计划</el-button></div>
    </template>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../../api/client'
import { useOperationsStore } from '../../stores/useOperationsStore'
const props = defineProps({ plans: { type: Array, default: () => [] } })
const emit = defineEmits(['close'])
const store = useOperationsStore()
const source = ref(store.instance ? 'current' : 'production'), planId = ref(''), solver = ref(''), unit = ref('hours')
const preview = ref(null), checking = ref(false), error = ref(''), previewRun = ref(null)
const stages = { production: '生产', material: '物料', assembly: '组装', delivery: '配送' }
const selectedPlan = computed(() => props.plans.find(p => p.id === planId.value))
watch(() => props.plans, plans => { if (!plans.some(p => p.id === planId.value)) planId.value = plans.find(p => p.id === store.productionSource?.plan_id)?.id || plans.find(p => p.can_preview)?.id || '' }, { immediate: true })
watch(selectedPlan, plan => { solver.value = plan?.solvers.includes(plan?.recommended_solver) ? plan.recommended_solver : plan?.solvers[0] || ''; unit.value = plan && plan.id === store.productionSource?.plan_id ? store.productionSource?.time_unit || 'hours' : 'hours' }, { immediate: true, flush: 'sync' })
watch([planId, solver, unit], () => { preview.value = null; error.value = '' }, { flush: 'sync' })
const body = () => ({ source: 'production', plan_id: planId.value, solver_id: solver.value, time_unit: unit.value })
function fail(e) { error.value = String(e.response?.data?.detail || e.message || e) }
async function check() {
  checking.value = true; error.value = ''; preview.value = null
  const selection = JSON.stringify(body()), run = store.instance?.run_id || null
  try {
    const result = (await api.post('/api/operations-tools/plans/preview', JSON.parse(selection))).data
    if (selection !== JSON.stringify(body()) || run !== (store.instance?.run_id || null)) { error.value = '计划或案例已变化，请重新预览'; return }
    preview.value = result; previewRun.value = run
  } catch(e) { fail(e) } finally { checking.value = false }
}
async function activate() {
  try {
    if (!preview.value?.can_activate) return
    if (previewRun.value !== (store.instance?.run_id || null)) throw new Error('案例已变化，请重新预览')
    const request = { ...body(), source_version: preview.value.source_version, ...(previewRun.value ? { archive_previous: true, previous_run_id: previewRun.value } : {}) }
    await ElMessageBox.confirm(store.instance ? '归档本轮，启用仅含生产环节的新计划？' : '按当前时间启用生产计划？', '启用生产计划', { confirmButtonText: '启用', cancelButtonText: '返回' })
    const result = await store.activate(request)
    if (result.status === 'done') { emit('close'); ElMessage.success('生产计划已启用') }
    else ElMessage.info('正在提交，请在运行记录中查看')
  } catch(e) { if (e !== 'cancel' && e !== 'close') fail(e) }
}
async function restart() {
  try {
    const runId = store.instance?.run_id
    await ElMessageBox.confirm('归档本轮进度和故障，从当前时间重新运行原案例？', '重开案例', { confirmButtonText: '重新开始', cancelButtonText: '返回' })
    if (runId !== store.instance?.run_id) throw new Error('案例已变化，请重新选择')
    const result = await store.reloadCase()
    if (result.status === 'done') { emit('close'); ElMessage.success('新一轮已开始') }
    else ElMessage.info('正在提交，请在运行记录中查看')
  } catch(e) { if (e !== 'cancel' && e !== 'close') fail(e) }
}
</script>
<style scoped>
.quick-setup{max-width:620px;margin:15px auto 0}.source-options{display:flex;gap:12px;margin:20px 0}.source-options button{flex:1;text-align:left;border:1px solid #e0e7f1;background:#fff;border-radius:9px;padding:16px;cursor:pointer;color:#657b98}.source-options button.active{border-color:#77a2df;background:#f3f7fe}.source-options b{display:block;font-size:14px;color:#41618b}.source-options span{display:block;font-size:12px;margin-top:7px;color:#8798af}.case-card,.preview-card{background:#f7f9fc;border-radius:8px;padding:18px;font-size:14px;color:#567194}.coverage{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.case-card p,.hint,.preview-card p{font-size:12px;color:#8696ac;line-height:1.7}.preview-card span{display:block;margin-top:8px;font-size:12px}.quick-footer{display:flex;justify-content:flex-end;gap:8px;margin-top:24px}.quick-footer :deep(.el-button+.el-button){margin-left:0}.full{width:100%}.settings{display:flex;gap:12px;padding:8px 0}.quick-setup :deep(.el-alert){margin-top:15px}
</style>
