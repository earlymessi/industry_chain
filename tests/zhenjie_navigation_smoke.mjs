// Run from the repository root: node tests/zhenjie_navigation_smoke.mjs
import fs from 'node:fs'
import vm from 'node:vm'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const Vue = require('vue')
const { compile } = require('@vue/compiler-dom')
const html = fs.readFileSync(new URL('../zhenjie/vrp_lab.html', import.meta.url), 'utf8')
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1]
const template = html.match(/<div id="app" v-cloak>([\s\S]*)<\/div>\s*<script>/)[1]
compile(template, { mode: 'function' })

let api
const mounted = []
const unmounted = []
const handlers = new Map()
const requests = []
const messages = []
const parent = { postMessage: (data, origin) => messages.push({ data, origin }) }
const windowMock = {
  parent,
  addEventListener: (type, fn) => handlers.set(type, fn),
  removeEventListener: type => handlers.delete(type),
}
const context = {
  Vue: {
    ...Vue,
    createApp: options => ({ mount: () => { api = options.setup() } }),
    onMounted: fn => mounted.push(fn),
    onUnmounted: fn => unmounted.push(fn),
  },
  URLSearchParams,
  location: { origin: 'http://localhost:8008', pathname: '/logistics-vrp/', search: '?embed=1&tab=map' },
  window: windowMock,
  console,
  setInterval: () => 1,
  clearInterval: () => {},
  fetch: async url => {
    requests.push(url)
    const data = url.includes('/api/config') ? { defaults: { T: 5 }, mongo: { connected: true } }
      : url.includes('/api/status') ? { status: 'idle' }
      : url.includes('/api/orders/stats') ? { total: 0, by_day: [] }
      : url.includes('/api/orders?') ? { items: [] }
      : url.includes('/api/results') ? { status: 'cached', data: { summary: [] } } : {}
    return { ok: true, json: async () => data }
  },
  alert: message => { throw new Error(message) },
  confirm: () => false,
}

vm.runInNewContext(script, context)
for (const fn of mounted) await fn()
assert.equal(api.page.value, 'map')
api.form.n_runs = 3
handlers.get('message')({ source: parent, origin: context.location.origin, data: { type: 'zhenjie-tab', tab: 'orders' } })
await new Promise(resolve => setImmediate(resolve))
assert.equal(api.page.value, 'orders')
assert.ok(requests.some(url => url.startsWith('/logistics-vrp/api/orders?')))
assert.ok(messages.some(message => message.data.type === 'zhenjie-tab-changed' && message.data.tab === 'orders'))
handlers.get('message')({ source: parent, origin: 'https://example.com', data: { type: 'zhenjie-tab', tab: 'charts' } })
assert.equal(api.page.value, 'orders')
handlers.get('message')({ source: parent, origin: context.location.origin, data: { type: 'zhenjie-tab', tab: 'experiment' } })
await Vue.nextTick()
assert.equal(api.page.value, 'experiment')
assert.equal(api.form.n_runs, 3, 'Switching to orders must preserve edited experiment settings')
assert.ok(requests.every(url => url.startsWith('/logistics-vrp/')))
for (const fn of unmounted) fn()
assert.equal(handlers.size, 0)
console.log('Passed: template compilation, initial tab, navigation, order loading, settings preservation and API prefix.')
