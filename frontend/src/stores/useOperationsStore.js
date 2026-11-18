import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../api/client'
import { isCurrentOperationsAdjustment } from '../utils/operationsPlan'

const root = '/api/operations-tools'
const id = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export const useOperationsStore = defineStore('operations', () => {
  const payload = ref(null)
  const connected = ref(false)
  const error = ref('')
  const now = ref(Date.now() / 1000)
  const history = ref({ events: [], adjustments: [] })
  const adjustment = ref(null), historyView = ref(false)
  let adjustmentWatch=0
  const busy = ref(false)
  const productionSource = ref(null)
  const archives = ref([])
  let stream = null, timer = null, poll = null, historyTimer = null, sourceTimer = null, anchor = null, monotonic = 0
  const instance = computed(() => payload.value?.instance)
  const stale = computed(() => historyView.value || !isCurrentOperationsAdjustment(adjustment.value,instance.value) || adjustment.value?.stale || (adjustment.value?.run_id && adjustment.value.run_id !== instance.value?.run_id) || (adjustment.value?.result?.candidates?.[0]?.constraint_version != null && adjustment.value.result.candidates[0].constraint_version !== instance.value?.constraint_version))
  function syncClock(value) {
    if (!Number.isFinite(value)) return
    anchor = value
    monotonic = performance.now()
    now.value = value
  }
  function accept(data) {
    if (payload.value?.instance?.run_id && payload.value.instance.run_id !== data.instance?.run_id) {
      clearAdjustment()
    }
    syncClock(data.server_timestamp)
    payload.value = data
    if (!historyView.value && adjustment.value && !isCurrentOperationsAdjustment(adjustment.value,instance.value)) clearAdjustment()
    error.value = ''
  }
  async function refresh() {
    try { accept((await api.get(`${root}/current`)).data) }
    catch (e) { error.value = e.response?.data?.detail || e.message; throw e }
  }
  async function loadHistory() {
    const run=instance.value?.run_id
    const data=(await api.get(`${root}/history`)).data
    if (run!==instance.value?.run_id || (data.run_id && data.run_id!==run)) return
    history.value=data
  }
  function clearAdjustment() { clearInterval(poll); adjustmentWatch++; adjustment.value=null; historyView.value=false }
  function restoreCurrentAdjustment() {
    historyView.value=false
    if (isCurrentOperationsAdjustment(adjustment.value,instance.value)) return
    clearAdjustment()
    const latest=[...(history.value.adjustments || [])].filter(j=>isCurrentOperationsAdjustment(j,instance.value)).sort((a,b)=>b.created_at-a.created_at)[0]
    if(latest) watchAdjustment(latest.id)
  }
  async function refreshProductionSource() {
    try { productionSource.value = (await api.get(`${root}/plans/production/status`)).data }
    catch { productionSource.value = { status: 'unavailable', message: '来源状态暂不可用，可在生产来源中重试' } }
    return productionSource.value
  }
  async function fetchAdjustment(jid, token=adjustmentWatch, historical=historyView.value) {
    const run=instance.value?.run_id
    const job=(await api.get(`${root}/adjustments/${jid}`)).data
    if(token!==adjustmentWatch || run!==instance.value?.run_id) return null
    if(!historical && !isCurrentOperationsAdjustment(job,instance.value)){clearAdjustment();return null}
    adjustment.value=job
    return job
  }
  function watchAdjustment(jid, {history:historical=false}={}) {
    clearInterval(poll)
    const token=++adjustmentWatch
    historyView.value=historical;if(adjustment.value?.id!==jid)adjustment.value=null
    const update=async()=>{
      try {
        const job=await fetchAdjustment(jid,token,historical)
        if(token!==adjustmentWatch)return
        if(job && ['done','failed'].includes(job.status)){clearInterval(poll);await loadHistory()}
      }catch(e){if(token===adjustmentWatch){clearInterval(poll);error.value=e.message}}
    }
    poll=setInterval(update,1500)
    update()
  }
  async function connect() {
    disconnect()
    await refresh()
    timer = setInterval(() => { if (anchor != null) now.value = anchor + (performance.now() - monotonic) / 1000 }, 250)
    stream = new EventSource(`${root}/stream`)
    stream.addEventListener('snapshot', (event) => { accept(JSON.parse(event.data)); connected.value = true })
    stream.addEventListener('heartbeat', (event) => {
      const data = JSON.parse(event.data)
      syncClock(data.server_timestamp)
      if (payload.value) payload.value.health = data.health
      connected.value = true
    })
    stream.onerror = () => { connected.value = false }
    await loadHistory()
    await refreshProductionSource()
    historyTimer = setInterval(() => loadHistory().catch((e) => { error.value = e.message }), 10000)
    sourceTimer = setInterval(refreshProductionSource, 15000)
    restoreCurrentAdjustment()
  }
  function disconnect() {
    stream?.close(); stream = null; connected.value = false
    clearInterval(timer); clearInterval(poll); adjustmentWatch++; clearInterval(historyTimer); clearInterval(sourceTimer)
  }
  async function command(path, body) {
    const request = { ...body, request_id: id() }
    let result = (await api.post(`${root}${path}`, request)).data
    for (let n = 0; !body.scheduled_at && result.status === 'queued' && n < 20; n++) {
      await delay(500)
      result = (await api.get(`${root}/commands/${result.command_id}`)).data
    }
    await refresh(); await loadHistory(); await refreshProductionSource()
    return result
  }
  async function loadArchives() { archives.value = (await api.get(`${root}/cases/archives`)).data.runs }
  async function reloadCase() {
    busy.value = true
    try { const result = await command('/cases/reload', { run_id: instance.value.run_id, confirmed: true }); await loadArchives(); return result }
    finally { busy.value = false }
  }
  async function activate(body = {}) {
    busy.value = true
    try { return await command('/plans/activate', body) } finally { busy.value = false }
  }
  async function event(body) {
    busy.value = true
    try { return await command('/events', { ...body, run_id: instance.value.run_id }) } finally { busy.value = false }
  }
  async function generate() {
    const job = (await api.post(`${root}/adjustments`, { run_id: instance.value.run_id, request_id: id() })).data
    adjustment.value = job
    watchAdjustment(job.id)
    return job
  }
  async function syncProduction(previewId) {
    busy.value = true
    try { return await command('/plans/production/sync', { run_id: instance.value.run_id, preview_id: previewId }) }
    finally { busy.value = false }
  }
  async function apply(candidate) {
    busy.value = true
    try { return await command(`/adjustments/${adjustment.value.id}/apply`, { run_id: instance.value.run_id, candidate_id: candidate.id }) }
    finally { busy.value = false; if (adjustment.value) await fetchAdjustment(adjustment.value.id) }
  }
  return { historyView, clearAdjustment, restoreCurrentAdjustment, archives, loadArchives, reloadCase, payload, instance, connected, error, now, history, adjustment, stale, busy, productionSource, refreshProductionSource, syncProduction, connect, disconnect, refresh, loadHistory, activate, event, generate, apply, watchAdjustment }
})
