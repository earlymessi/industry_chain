<template>
  <div class="panorama">
    <div class="flow-wrap">
      <svg
        class="flow-svg"
        :viewBox="`0 0 ${layout.w} ${layout.h}`"
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          <marker id="chain-arrow" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto">
            <path d="M0,0 L10,5 L0,10 Z" fill="#475569" />
          </marker>
        </defs>

        <g v-for="zone in layout.zones" :key="zone.id">
          <rect
            :x="zone.x"
            :y="zone.y"
            :width="zone.w"
            :height="zone.h"
            rx="10"
            :fill="zone.fill"
            :stroke="zone.stroke"
            stroke-width="1.5"
            stroke-dasharray="6 4"
          />
          <text
            :x="zone.x + zone.w / 2"
            :y="zone.y + 22"
            text-anchor="middle"
            :fill="zone.titleColor"
            font-size="14"
            font-weight="700"
          >
            {{ zone.title }}
          </text>
        </g>

        <g
          v-for="(s, i) in layout.suppliers"
          :key="'sup-' + i"
          class="node clickable"
          @click="onSupplierClick(s)"
        >
          <rect :x="s.x" :y="s.y" :width="s.w" :height="s.h" rx="6" :fill="s.color" />
          <text
            :x="s.x + s.w / 2"
            :y="s.y + s.h / 2 + 4"
            text-anchor="middle"
            fill="#fff"
            font-size="12"
            font-weight="600"
          >
            {{ s.short }}
          </text>
        </g>

        <g
          v-for="node in layout.nodes"
          :key="node.id"
          class="node"
          :class="{ clickable: node.route, highlight: node.highlight, dim: node.dim }"
          @click="onNodeClick(node)"
        >
          <rect
            :x="node.x"
            :y="node.y"
            :width="node.w"
            :height="node.h"
            rx="7"
            :fill="node.fill"
            :stroke="node.stroke"
            stroke-width="2"
          />
          <text
            :x="node.x + node.w / 2"
            :y="node.y + node.h / 2 + (node.sub ? -4 : 5)"
            text-anchor="middle"
            :fill="node.titleColor"
            :font-size="node.fontSize || 13"
            font-weight="600"
          >
            {{ node.title }}
          </text>
          <text
            v-if="node.sub"
            :x="node.x + node.w / 2"
            :y="node.y + node.h / 2 + 15"
            text-anchor="middle"
            :fill="node.subColor"
            font-size="11"
          >
            {{ node.sub }}
          </text>
        </g>

        <g v-if="layout.product">
          <rect
            :x="layout.product.x"
            :y="layout.product.y"
            :width="layout.product.w"
            :height="layout.product.h"
            rx="7"
            fill="#e0e7ff"
            stroke="#6366f1"
            stroke-width="2"
          />
          <text
            :x="layout.product.x + layout.product.w / 2"
            :y="layout.product.y + layout.product.h / 2 - 2"
            text-anchor="middle"
            fill="#4338ca"
            font-size="13"
            font-weight="700"
          >
            成品
          </text>
          <text
            :x="layout.product.x + layout.product.w / 2"
            :y="layout.product.y + layout.product.h / 2 + 16"
            text-anchor="middle"
            fill="#6366f1"
            font-size="12"
          >
            家电
          </text>
        </g>

        <path
          v-for="(edge, i) in layout.edges"
          :key="'e-' + i"
          :d="edge.d"
          fill="none"
          :stroke="edge.color || '#475569'"
          stroke-width="2.5"
          marker-end="url(#chain-arrow)"
        />
      </svg>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  paretoCount: { type: Number, default: 0 },
  batchOrderCount: { type: Number, default: 0 },
  referenceEtptH: { type: Number, default: null },
  referenceTc: { type: Number, default: null },
  kdceaStatus: { type: String, default: 'idle' },
  hasReferencePlan: { type: Boolean, default: false },
  assemblyAvailable: { type: Boolean, default: true },
  supplierPerformance: { type: Array, default: () => [] },
  inTransitCount: { type: Number, default: 0 },
  shortageCount: { type: Number, default: 0 },
  executionStatus: { type: String, default: 'idle' },
  readinessStatus: { type: String, default: '' },
})

const emit = defineEmits(['navigate'])

const SUPPLIER_COLORS = ['#ef4444', '#3b82f6', '#a78bfa', '#22c55e', '#f59e0b', '#6b7280']
const DEFAULT_SUPPLIERS = [
  { short: '压缩机' },
  { short: '电气元件' },
  { short: '钣金外协' },
  { short: '发泡料' },
  { short: '门体配件' },
  { short: '包装材料' },
]

const kdceaRunning = computed(() => props.kdceaStatus === 'running')
const mesActive = computed(() => ['running', 'paused', 'completed'].includes(props.executionStatus))
const asmActive = computed(() => ['ready', 'consumed'].includes(props.readinessStatus))

const optimizeStatusLabel = computed(() => {
  const map = { running: '计算中', done: '已完成', completed: '已完成', error: '异常', idle: '待命' }
  return map[props.kdceaStatus] || props.kdceaStatus || '待命'
})

function spread(count, left, right, boxSize) {
  if (count <= 0) return []
  if (count === 1) return [left + (right - left - boxSize) / 2]
  const gap = (right - left - count * boxSize) / (count - 1)
  return Array.from({ length: count }, (_, i) => left + i * (boxSize + gap))
}

/** 在区域内铺网格；末行不足列数时居中 */
function placeInZone(items, zone, cols, topPad = 36, pad = 14, gap = 12) {
  const n = items.length
  if (!n) return []
  const rows = Math.ceil(n / cols)
  const innerLeft = zone.x + pad
  const innerRight = zone.x + zone.w - pad
  const innerTop = zone.y + topPad
  const innerBottom = zone.y + zone.h - pad
  const innerW = innerRight - innerLeft
  const innerH = innerBottom - innerTop
  const cellW = Math.floor((innerW - gap * (cols - 1)) / cols)
  const cellH = Math.floor((innerH - gap * (rows - 1)) / rows)
  const slots = []

  for (let i = 0; i < n; i++) {
    const row = Math.floor(i / cols)
    const colInRow = i % cols
    const itemsInRow = row === rows - 1 ? n - row * cols : cols
    const rowCols = Math.min(cols, itemsInRow)
    const rowW = rowCols * cellW + (rowCols - 1) * gap
    const rowLeft = innerLeft + (innerW - rowW) / 2
    const x = rowLeft + colInRow * (cellW + gap)
    const y = innerTop + row * (cellH + gap)
    slots.push({ x, y, w: cellW, h: cellH })
  }
  return slots
}

function mkNode(id, title, rect, route, style = {}) {
  return {
    id,
    title,
    x: rect.x,
    y: rect.y,
    w: rect.w,
    h: rect.h,
    route,
    fill: style.fill || '#fff',
    stroke: style.stroke || '#cbd5e1',
    titleColor: style.titleColor || '#334155',
    sub: style.sub,
    subColor: style.subColor || '#64748b',
    highlight: style.highlight || false,
    dim: style.dim || false,
    fontSize: style.fontSize || 13,
  }
}

const layout = computed(() => {
  const W = 1400
  const H = 540
  const pad = 16
  const rowGap = 14

  const scH = 108
  const scY = pad
  const scZone = {
    id: 'sc',
    title: '供应链订单调度',
    x: pad,
    y: scY,
    w: W - pad * 2,
    h: scH,
    fill: '#fff7ed',
    stroke: '#fb923c',
    titleColor: '#c2410c',
  }

  const mainY = scY + scH + rowGap
  const mainH = H - mainY - pad
  const mainW = W - pad * 2
  const colGap = 14
  const colRatios = [0.24, 0.38, 0.38]
  const colWs = colRatios.map((r) => Math.floor(mainW * r - colGap * 2 / 3))

  const supZone = {
    id: 'sup',
    title: '外协供应商资源管控',
    x: pad,
    y: mainY,
    w: colWs[0],
    h: mainH,
    fill: '#fff5f5',
    stroke: '#ef4444',
    titleColor: '#b91c1c',
  }
  const prodZone = {
    id: 'prod',
    title: '生产资源管控',
    x: pad + colWs[0] + colGap,
    y: mainY,
    w: colWs[1],
    h: mainH,
    fill: '#eff6ff',
    stroke: '#3b82f6',
    titleColor: '#1d4ed8',
  }
  const asmZone = {
    id: 'asm',
    title: '组装资源管控',
    x: prodZone.x + colWs[1] + colGap,
    y: mainY,
    w: colWs[2],
    h: mainH,
    fill: '#f0fdf4',
    stroke: '#22c55e',
    titleColor: '#15803d',
  }

  const zones = [scZone, supZone, prodZone, asmZone]

  const scBoxW = 158
  const scBoxH = 58
  const scXs = spread(6, scZone.x + 14, scZone.x + scZone.w - 14, scBoxW)
  const scYNode = scZone.y + 40

  const scDefs = [
    ['sc-params', '参数设置', '/home/supply-chain/params', {}],
    ['sc-input', '信息录入', '/home/supply-chain/order-input', {}],
    ['sc-orders', '订单管理', '/home/supply-chain/orders', {
      fill: kdceaRunning.value ? '#fef3c7' : '#fff',
      stroke: kdceaRunning.value ? '#f59e0b' : '#cbd5e1',
      titleColor: kdceaRunning.value ? '#92400e' : '#334155',
      highlight: kdceaRunning.value,
    }],
    ['sc-optimize', '全局优化求解', '/home/supply-chain/orders', {
      fill: kdceaRunning.value ? '#fef3c7' : '#eff6ff',
      stroke: '#3b82f6',
      titleColor: '#1d4ed8',
      sub: optimizeStatusLabel.value,
      highlight: kdceaRunning.value,
    }],
    ['sc-route', '配送路径规划', '/home/supply-chain/dashboard', {
      fill: props.hasReferencePlan ? '#f0fdf4' : '#fff',
      stroke: props.hasReferencePlan ? '#22c55e' : '#cbd5e1',
      highlight: props.hasReferencePlan,
    }],
    ['sc-ref', '调度参考方案', '/home/supply-chain/dashboard', {
      fill: '#fff7ed',
      stroke: '#fb923c',
      titleColor: '#c2410c',
      sub: props.referenceEtptH != null ? `参考交期 ${Number(props.referenceEtptH).toFixed(1)}h` : '',
      highlight: props.hasReferencePlan,
    }],
  ]

  const scNodes = scDefs.map(([id, title, route, style], i) =>
    mkNode(id, title, { x: scXs[i], y: scYNode, w: scBoxW, h: scBoxH }, route, style),
  )

  const src = props.supplierPerformance.length ? props.supplierPerformance : DEFAULT_SUPPLIERS
  const supList = src.slice(0, 6).map((s, i) => ({
    short: (s.short_name || s.short || s.name || '').slice(0, 8),
    color: SUPPLIER_COLORS[i % SUPPLIER_COLORS.length],
  }))

  const supPad = 12
  const hubH = 52
  const kitH = 48
  const hubY = supZone.y + supZone.h - supPad - kitH - 10 - hubH
  const supAreaTop = supZone.y + 34
  const supAreaBottom = hubY - 10
  const supBoxH = Math.max(28, Math.floor((supAreaBottom - supAreaTop - (supList.length - 1) * 8) / supList.length))
  const supTotalH = supList.length * supBoxH + (supList.length - 1) * 8
  const supStartY = supAreaTop + (supAreaBottom - supAreaTop - supTotalH) / 2

  const suppliers = supList.map((s, i) => ({
    ...s,
    x: supZone.x + supPad,
    y: supStartY + i * (supBoxH + 8),
    w: supZone.w - supPad * 2,
    h: supBoxH,
    route: '/home/outsourced-supply',
  }))

  const hubX = supZone.x + supPad
  const hubW = supZone.w - supPad * 2
  const whNode = mkNode('warehouse', '中央仓库', { x: hubX, y: hubY, w: hubW, h: hubH }, '/home/outsourced-supply', {
    fill: '#fef3c7',
    stroke: '#f59e0b',
    titleColor: '#92400e',
    sub: '齐套缓存',
    fontSize: 13,
  })
  const kitNode = mkNode('kitting', '齐套衔接', { x: hubX, y: hubY + hubH + 10, w: hubW, h: kitH }, null, {
    fill: props.readinessStatus ? '#ecfdf5' : '#f8fafc',
    stroke: props.readinessStatus ? '#10b981' : '#cbd5e1',
    titleColor: '#047857',
    sub: props.readinessStatus === 'ready' ? '待组装' : props.readinessStatus === 'consumed' ? '已消费' : '待命',
    highlight: !!props.readinessStatus,
    fontSize: 13,
  })

  const prodDefs = [
    ['prod-dash', '生产看板', '/home/production/dashboard'],
    ['prod-aps', '智能排程', '/home/production/aps'],
    ['prod-log', 'AGV 物流', '/home/production/logistics'],
    ['prod-nrg', '能耗管控', '/home/production/energy'],
    ['prod-hlt', '设备健康', '/home/production/health'],
    ['prod-mat', '加工物料', '/home/production/materials'],
    ['prod-rpt', '分析报表', '/home/production/reports'],
    ['prod-db', '数据中心', '/home/production/database'],
  ]
  const prodSlots = placeInZone(prodDefs, prodZone, 4)
  const prodNodes = prodDefs.map(([id, title, route], i) =>
    mkNode(id, title, prodSlots[i], route, {
      fill: mesActive.value ? '#dbeafe' : '#fff',
      stroke: mesActive.value ? '#3b82f6' : '#cbd5e1',
      titleColor: mesActive.value ? '#1d4ed8' : '#334155',
      fontSize: 13,
      highlight: mesActive.value && (id === 'prod-dash' || id === 'prod-aps'),
    }),
  )

  const productW = 56
  const productH = 96
  const asmInnerZone = {
    ...asmZone,
    w: asmZone.w - productW - 16,
  }
  const asmDefs = [
    ['asm-dash', '组装看板', '/home/assembly/dashboard'],
    ['asm-mat', '物料管理', '/home/assembly/materials'],
    ['asm-gantt', '甘特排程', '/home/assembly/gantt'],
    ['asm-agent', '排程仿真', '/home/assembly/dynamic'],
    ['asm-chart', '数据统计', '/home/assembly/charts'],
  ]
  const asmSlots = placeInZone(asmDefs, asmInnerZone, 3)
  const asmNodes = asmDefs.map(([id, title, route], i) =>
    mkNode(id, title, asmSlots[i], route, {
      fill: asmActive.value ? '#dcfce7' : '#fff',
      stroke: asmActive.value ? '#22c55e' : '#cbd5e1',
      titleColor: asmActive.value ? '#15803d' : '#334155',
      fontSize: 13,
      dim: !props.assemblyAvailable,
      highlight: asmActive.value && id === 'asm-dash',
    }),
  )

  const product = {
    x: asmZone.x + asmZone.w - productW - 10,
    y: asmZone.y + (asmZone.h - productH) / 2,
    w: productW,
    h: productH,
  }

  const scMidY = scYNode + scBoxH / 2
  const hubMidX = supZone.x + supZone.w / 2
  const hubMidY = hubY + hubH / 2
  const prodMidY = prodZone.y + prodZone.h / 2
  const asmMidY = asmZone.y + asmZone.h / 2

  const edges = []
  for (let i = 0; i < 5; i++) {
    edges.push({ d: `M ${scXs[i] + scBoxW} ${scMidY} H ${scXs[i + 1]}` })
  }

  edges.push({ d: `M ${supZone.x + supZone.w} ${hubMidY} H ${prodZone.x}` })
  edges.push({ d: `M ${prodZone.x + prodZone.w} ${prodMidY} H ${asmZone.x}` })
  edges.push({ d: `M ${asmInnerZone.x + asmInnerZone.w} ${asmMidY} H ${product.x}` })

  return {
    w: W,
    h: H,
    zones,
    suppliers,
    nodes: [...scNodes, whNode, kitNode, ...prodNodes, ...asmNodes],
    product,
    edges,
  }
})

function onNodeClick(node) {
  if (!node.route) return
  if ((node.route.startsWith('/home/assembly') || node.route.startsWith('/assembly')) && !props.assemblyAvailable) return
  emit('navigate', node.route)
}

function onSupplierClick(s) {
  if (s.route) emit('navigate', s.route)
}
</script>

<style scoped>
.panorama {
  width: 100%;
}

.flow-wrap {
  background: linear-gradient(180deg, #fafbfc 0%, #f1f5f9 100%);
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px;
  overflow-x: auto;
}

.flow-svg {
  width: 100%;
  min-height: 580px;
  height: clamp(580px, 65vh, 800px);
  display: block;
}

.node.clickable {
  cursor: pointer;
}

.node.clickable:hover rect {
  filter: brightness(0.96);
  stroke-width: 2.5;
}

.node.highlight rect {
  filter: drop-shadow(0 2px 6px rgba(59, 130, 246, 0.22));
}

.node.dim {
  opacity: 0.5;
}
</style>
