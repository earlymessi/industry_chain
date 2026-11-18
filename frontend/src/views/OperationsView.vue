<template>
  <div class="operations-page">
    <header class="page-header">
      <div>
        <div class="plan-caption"><span :class="['live-dot', { offline: !online }]"></span>{{ !online ? '等待连接' : !instance ? '服务在线' : instance.status === 'idle' ? '任务已完成' : instance.tasks.some(t => t.status === 'running') ? '执行中' : instance.resources.some(r => !r.available) ? '等待资源恢复' : '等待任务条件' }}</div>
      </div>
      <div class="header-actions">
        <div class="clock"><b>{{ clockTime }}</b><small>北京时间</small></div>
        <el-button type="primary" plain @click="chainOpen = true">计划配置</el-button>
        <el-dropdown trigger="click" @command="handleMenu">
          <el-button aria-label="更多操作">更多<el-icon class="menu-arrow"><ArrowDown /></el-icon></el-button>
          <template #dropdown><el-dropdown-menu>
            <el-dropdown-item command="source">生产来源</el-dropdown-item>
            <el-dropdown-item command="reload" :disabled="!instance || !online || store.busy">重开案例</el-dropdown-item>
            <el-dropdown-item command="history">运行记录</el-dropdown-item>
            <el-dropdown-item command="refresh" divided>刷新状态</el-dropdown-item>
          </el-dropdown-menu></template>
        </el-dropdown>
      </div>
    </header>
    <el-alert v-if="store.error" :title="String(store.error)" type="error" :closable="false" show-icon class="notice" />
    <el-alert v-if="!online && store.payload" title="状态待同步，请连接恢复后操作。" type="warning" :closable="false" show-icon class="notice" />
    <div v-if="instance && store.productionSource?.has_updates" class="source-bar"><span>生产计划有更新</span><el-button link type="primary" @click="previewLinkedSource">查看并同步</el-button></div>
    <div v-if="legacyBaseline" class="legacy-notice"><span>当前案例需关联原系统计划。</span><el-button type="primary" size="small" @click="manageOpen = true">选择计划</el-button></div>

    <section class="stage-flow" aria-label="产业链环节">
      <button v-for="s in stages" :key="s.id" class="stage-card" :class="{ active: stage === s.id, attention: s.issues > 0 }" :disabled="instance?.plan.coverage?.[s.id] === 'unbound'" :style="{ '--stage-color': s.color }" :aria-pressed="stage === s.id" @click="selectStage(s.id)">
        <div class="stage-title"><span class="stage-icon"><component :is="s.icon" /></span><b>{{ s.name }}</b><el-tag v-if="s.issues" type="warning" size="small">{{ s.issues }} 待处理</el-tag></div>
        <div class="stage-bottom"><span>{{ instance?.plan.coverage?.[s.id] === 'unbound' ? '未接入' : instance?.plan.coverage?.[s.id] === 'not_provided' ? '缺少BOM' : instance ? `${s.done}/${s.total} ${s.id === 'material' ? '供给确认' : '完成'}` : '待启用' }}</span><span v-if="instance && !['unbound', 'not_provided'].includes(instance.plan.coverage?.[s.id])">{{ s.running }} {{ s.id === 'material' ? '批待确认' : '执行中' }}</span></div>
      </button>
    </section>

    <div class="workbench">
      <main class="plan-area">
        <section class="surface plan-panel">
          <div class="panel-heading"><div class="heading-inline"><h2>{{ stage === 'all' ? '全链路计划' : `${stageNames[stage]}计划` }}</h2><button v-if="stage !== 'all'" class="text-button" @click="stage = 'all'">查看全链路</button></div>
            <div class="grain-switch" aria-label="计划时间粒度"><button v-for="g in grains" :key="g.hours" :class="{ active: hours === g.hours }" :aria-pressed="hours === g.hours" @click="hours = g.hours">{{ g.label }}</button></div>
          </div>
          <template v-if="!instance">
            <div class="start-plan"><div class="start-icon"><Calendar /></div><h3>选择计划，开始运维</h3><el-button type="primary" size="large" :disabled="!online" @click="chainOpen = true">配置产业链计划</el-button><button class="text-button" :disabled="!online" @click="openProductionSource">仅接入生产计划</button></div>
          </template>
          <template v-else>
            <div class="plan-strip"><span>{{ rangeLabel }}<em>{{ hours === 4 ? '工序级' : hours === 24 ? '当日工序' : hours === 168 ? '按日刻度' : '按周刻度' }}</em></span><span>完成 <b>{{ completed }}/{{ instance.tasks.length }}</b><i>·</i>{{ instance.plan.scope === 'production' ? '工单完工' : '交付' }} <b>{{ delivered }}/{{ businessOrders.length }}</b><i>·</i><span v-if="currentCommitments.unknownDue">未设交期 <b>{{ currentCommitments.unknownDue }} 单</b></span><span v-else>预计延期 <b :class="{ warning: currentCommitments.unknownCompletion || currentCommitments.delaySeconds > 0 }">{{ currentCommitments.unknownCompletion ? '完工待评估' : `${minutes(currentCommitments.delaySeconds)} 分` }}</b></span></span></div>
            <el-alert v-if="instance.forecast?.status === 'unresolved'" title="任务受阻，需调整计划。" type="warning" :closable="false" show-icon class="notice" />
            <div class="timeline-wrap"><OperationsTimeline :instance="instance" :now="store.now" :window="viewWindow" :stage="stage" @navigate="navigateTimeline" @resume="resumeTimeline" @select="openTaskEvent" @supply="openEvent('supply_delay', $event.id, 'material')" /><div class="legend"><span><i class="actual"></i>已执行</span><span><i class="forecast"></i>{{ instance.forecast?.status === 'available' ? '预计安排' : '原安排' }}</span><span><i class="now"></i>当前时间</span></div></div>
            <div class="panel-heading task-heading"><h2>{{ stage === 'material' ? '供给计划' : '任务明细' }}</h2><span v-if="hours >= 168" class="muted">仅展示已导入计划</span></div>
            <template v-if="stage === 'material'">
              <el-table :data="windowSupplies" size="small" empty-text="此时间范围没有到货计划"><el-table-column prop="name" label="供给批次" min-width="170" /><el-table-column prop="quantity" label="数量" width="70" /><el-table-column label="供给节点时间" width="140"><template #default="{ row }">{{ fmt(row.available_at, true) }}</template></el-table-column><el-table-column label="状态" width="90"><template #default="{ row }"><el-tag size="small" :type="instance.received_supplies.includes(row.id) ? 'success' : 'info'">{{ instance.received_supplies.includes(row.id) ? (row.role === 'supplier_ready' ? '已备货' : '已收到') : (row.role === 'supplier_ready' ? '待备货' : '待到货') }}</el-tag></template></el-table-column><el-table-column label="运维" width="100"><template #default="{ row }"><el-button link type="primary" :disabled="instance.received_supplies.includes(row.id)" @click="openEvent('supply_delay', row.id, 'material')">{{ row.role === 'supplier_ready' ? '调整备货' : '调整到货' }}</el-button></template></el-table-column></el-table>
            </template>
            <el-table v-else :data="visibleTasks" size="small" max-height="440" empty-text="此时间范围没有已排任务">
              <el-table-column label="任务" min-width="190"><template #default="{ row }"><b>{{ row.name }}</b><div class="muted">{{ row.order_id }} · {{ kinds[row.kind] }}</div></template></el-table-column>
              <el-table-column label="资源" width="125"><template #default="{ row }">{{ resourceName(row.resource_id) || '—' }}</template></el-table-column>
              <el-table-column label="计划时间" min-width="145"><template #default="{ row }">{{ fmt(row.start_at, hours >= 168) }}—{{ fmt(row.end_at, hours >= 168) }}</template></el-table-column>
              <el-table-column label="运行状态" min-width="130"><template #default="{ row }"><el-tag size="small" :type="statusTone(row)">{{ statusName(row) }}</el-tag><div v-if="row.blocked_reason" class="blocked-reason" :title="row.blocked_reason">{{ row.blocked_reason }}</div></template></el-table-column>
              <el-table-column label="运维" width="95"><template #default="{ row }"><el-button link type="primary" :disabled="row.status === 'completed'" @click="openTaskEvent(row)">调整</el-button></template></el-table-column>
            </el-table>
            <el-collapse v-if="hours >= 168" class="summary-collapse"><el-collapse-item title="查看负荷汇总">
              <el-table :data="buckets" size="small" @row-click="drillBucket" class="clickable-table" empty-text="暂无已导入计划">
                <el-table-column :label="hours === 672 ? '周计划' : '日期'" min-width="130"><template #default="{ row }"><b>{{ dayLabel(row.start) }}</b><span v-if="hours === 672">—{{ dayLabel(row.end - 1) }}</span></template></el-table-column>
                <el-table-column v-if="stage === 'all' || stage === 'production'" label="生产" width="65"><template #default="{ row }">{{ row.hasPlan ? row.production : '—' }}</template></el-table-column>
                <el-table-column v-if="stage === 'all' || stage === 'material'" label="到货" width="65"><template #default="{ row }">{{ row.hasPlan ? row.supplyCount : '—' }}</template></el-table-column>
                <el-table-column v-if="stage === 'all' || stage === 'assembly'" label="组装" width="65"><template #default="{ row }">{{ row.hasPlan ? row.assembly : '—' }}</template></el-table-column>
                <el-table-column v-if="stage === 'all' || stage === 'delivery'" label="配送" width="65"><template #default="{ row }">{{ row.hasPlan ? row.delivery : '—' }}</template></el-table-column>
                <el-table-column v-if="stage !== 'material'" label="计划占用" min-width="100"><template #default="{ row }">{{ row.hasPlan && row.loadHours != null ? `${row.loadHours.toFixed(1)} 小时` : '—' }}</template></el-table-column>
                <el-table-column label="状态" min-width="150"><template #default="{ row }"><span class="muted">{{ !row.hasPlan ? '未导入后续计划' : row.calendarHours == null && stage !== 'material' ? '需补充资源日历' : '查看计划明细 →' }}</span></template></el-table-column>
              </el-table><div class="plan-footnote">{{ hours === 672 ? '四周为能力汇总' : '点击日期查看任务' }}</div>
            </el-collapse-item></el-collapse>
          </template>
        </section>

        <section v-if="instance" class="surface resource-panel">
          <div class="panel-heading resource-heading"><h2>{{ stage === 'material' ? '库存' : '资源' }} <small>{{ stage === 'material' ? Object.keys(instance.inventory).length : visibleResources.length }}</small></h2><button class="text-button" :aria-expanded="resourcesExpanded" @click="resourcesExpanded = !resourcesExpanded">{{ resourcesExpanded ? '收起' : '展开' }}</button></div>
          <div v-if="!resourcesExpanded && unavailableResources.length && stage !== 'material'" class="fault-shortcuts"><button v-for="r in unavailableResources" :key="r.id" @click="openEvent('resource_recovered', r.id)">{{ r.name }} · 确认恢复 →</button></div>
          <template v-if="resourcesExpanded">
          <div v-if="stage === 'material'" class="resource-list"><button v-for="(qty, key) in instance.inventory" :key="key" class="resource-tile" @click="openEvent('inventory_count', key, 'material')"><span><b :title="key">{{ inventoryLabel(key) }}</b></span><strong>{{ qty.toFixed(1) }}</strong></button></div>
          <div v-else class="resource-list"><button v-for="r in visibleResources" :key="r.id" class="resource-tile" :class="{ restricted: !r.available, picked: form.target_id === r.id }" @click="openEvent(r.available ? 'resource_unavailable' : 'resource_recovered', r.id)"><span><b>{{ r.name }}</b><small>{{ resourceWork(r.id) }}</small></span><span :class="r.available ? 'resource-ok' : 'warning'">{{ r.available ? '登记故障' : '确认恢复' }} →</span></button></div>
          </template>
        </section>
      </main>

      <aside ref="operationsPanel" class="surface operations-panel">
        <div class="operations-heading"><span class="operations-symbol"><Tools /></span><div><h2>运维操作</h2></div><el-tag size="small" effect="plain">{{agentStatus}}</el-tag></div>
        <template v-if="instance">
          <div class="agent-entry">
            <el-input v-model="question" type="textarea" :rows="3" maxlength="4000" placeholder="输入问题或运行变化，Enter 发送，Shift+Enter 换行" :disabled="asking" @keydown="onAgentKeydown" />
            <el-button type="primary" class="full agent-analyze" :loading="asking" :disabled="!online || !question.trim()" @click="askAssistant()">分析并给出建议</el-button>
            <div class="agent-shortcuts"><el-button size="small" :disabled="!online || asking" @click="askAssistant('巡检当前计划')">巡检</el-button><el-button size="small" :disabled="!online || asking" @click="askAssistant('分析当前已登记异常的影响')">分析影响</el-button></div>
            <p v-if="asking" class="agent-progress" role="status">正在读取运行状态并请求大模型…</p>
            <div v-if="assistantResult" class="agent-answer" aria-live="polite">
              <small v-if="assistantResult.status !== 'failed'" class="agent-answer-source">{{assistantResult.llm_used ? `AI 回答 · ${assistantResult.llm_model || '大模型'}` : '业务工具结果'}}</small>
              <p v-if="assistantResult.llm_message" class="warning">{{assistantResult.llm_message}}</p>
              <p class="agent-answer-text">{{assistantResult.summary}}</p>
              <div v-if="assistantResult.status !== 'failed'" class="agent-facts"><span>执行中 {{assistantResult.facts?.running?.length || 0}}</span><span>不可用资源 {{assistantResult.facts?.unavailable?.length || 0}}</span><span>阻塞 {{assistantResult.facts?.blocked?.length || 0}}</span></div>
              <p v-if="assistantResult.prepared_event?.draft" class="agent-confirm">已填入下方参数，请核对后确认提交。</p>
              <p v-for="item in assistantResult.prepared_event?.missing || []" :key="item" class="agent-confirm">{{item}}</p>
              <ul v-if="assistantResult.issues?.length" class="agent-issues"><li v-for="item in assistantResult.issues.slice(0,3)" :key="`${item.kind}:${item.target_id}`">{{item.name}}：{{item.message}}</li></ul>
              <el-collapse class="agent-evidence"><el-collapse-item title="查看依据"><small>{{fmt(assistantResult.checked_at,true)}} · {{assistantResult.llm_used ? '工具核验 + AI解释' : '工具核验'}} · {{instance.plan.mode === 'simulation' ? '执行模拟' : '运行反馈'}}</small><div v-for="(step,index) in agentSteps" :key="index" class="agent-step"><span>{{step.label}}</span><span>{{step.status}}</span></div></el-collapse-item></el-collapse>
            </div>
          </div>
          <div v-if="needsAdjustment" class="action-prompt"><span>有变化待调整</span><el-button link type="primary" :loading="jobRunning || generating" :disabled="!online" @click="generate">计算调整</el-button></div>
          <el-collapse v-model="manualSections" class="manual-entry"><el-collapse-item :title="assistantResult?.prepared_event?.draft ? '核对变化参数' : '手动录入 / 核对参数'" name="parameters">
          <el-form label-position="top" class="operations-form" @submit.prevent="submitEvent">
            <div class="form-step">环节</div>
            <el-select v-model="domain" aria-label="运维环节" class="full"><el-option v-for="(label, key) in domains" :key="key" :value="key" :label="label" :disabled="instance.plan.coverage?.[key] === 'unbound'" /></el-select>
            <el-form-item label="变化类型" class="action-select"><el-select v-model="form.type" aria-label="变化类型" class="full"><el-option v-for="a in actions[domain]" :key="a.type" :value="a.type" :label="a.label" :disabled="!actionEnabled(a.type)" /></el-select></el-form-item>
            <el-form-item :label="targetLabel"><el-select ref="targetSelect" v-model="form.target_id" filterable class="full" placeholder="请选择具体对象" aria-label="运维对象"><el-option v-for="t in targets" :key="t.id" :value="t.id" :label="t.label" /></el-select></el-form-item>

            <div v-if="originalValue" class="original-value">当前：{{ originalValue }}</div>
            <template v-if="form.type === 'resource_unavailable'"><el-form-item label="预计多久恢复"><div class="input-unit"><el-input-number v-model="form.recoveryMinutes" :min="1" :disabled="!form.knownRecovery" controls-position="right" /><span>分钟后</span></div><el-checkbox v-model="form.knownRecovery">已知预计时长</el-checkbox></el-form-item><p class="field-hint">修好后需确认恢复。</p></template>
            <div v-else-if="form.type === 'resource_recovered'" class="recovery-confirm">{{ resourceName(form.target_id) || '所选资源' }} 将恢复可用。</div>
            <template v-else-if="form.type === 'duration_change'"><el-form-item label="加工资源"><el-select v-model="form.resource_id" class="full" aria-label="工时作用资源"><el-option v-for="a in targetTask?.alternatives || []" :key="a.resource_id" :value="a.resource_id" :label="resourceName(a.resource_id)" /></el-select></el-form-item><el-form-item :label="`新工时（分钟/${targetTask?.duration_mode === 'per_unit' ? '件' : '批次'}）`"><el-input-number v-model="form.value" :min="0.001" :precision="3" :step="0.001" controls-position="right" /></el-form-item></template>
            <el-form-item v-else-if="['travel_change','service_change'].includes(form.type)" label="新耗时（分钟）"><el-input-number v-model="form.value" :min="form.type === 'service_change' ? 0 : 0.001" :precision="3" :step="0.001" controls-position="right" /></el-form-item>
            <el-form-item v-else-if="['supply_quantity','inventory_count'].includes(form.type)" label="新确认数量"><el-input-number v-model="form.value" :min="0" :precision="3" :step="0.001" controls-position="right" /></el-form-item>
            <el-form-item v-else-if="['supply_delay','release_change','order_change'].includes(form.type)" :label="form.type === 'order_change' ? '新交付承诺' : form.type === 'supply_delay' ? (instance.plan.supplies.find(s => s.id === form.target_id)?.role === 'supplier_ready' ? '新备货就绪时间' : '新预计到货时间') : '新最早开工时间'"><input type="datetime-local" v-model="form.at" class="date-input" /></el-form-item>
            <template v-else-if="form.type === 'window_change'"><el-form-item label="收货开始"><input type="datetime-local" v-model="form.at" class="date-input" /></el-form-item><el-form-item label="收货结束"><input type="datetime-local" v-model="form.until" class="date-input" /></el-form-item></template>
            <el-form-item v-if="form.type === 'order_change'" label="优先级"><el-input-number v-model="form.priority" :min="1" controls-position="right" /></el-form-item>
            <el-collapse class="optional-fields"><el-collapse-item title="更多设置" name="extra"><el-form-item label="备注"><el-input v-model="form.reason" placeholder="选填" /></el-form-item><el-checkbox v-model="form.scheduled">预约模拟变化</el-checkbox><input v-if="form.scheduled" type="datetime-local" v-model="form.scheduledAt" class="date-input" /><el-form-item label="来源"><el-select v-model="form.source" class="full"><el-option label="人工模拟" value="manual_simulation" /><el-option label="人工确认反馈" value="manual_feedback" /></el-select></el-form-item><el-form-item label="记录人"><el-input v-model="form.operator" /></el-form-item></el-collapse-item></el-collapse>
            <el-button class="submit-change" type="primary" native-type="submit" :loading="store.busy || generating" :disabled="!online || !form.target_id">{{ form.scheduled ? '预约变化' : form.type === 'resource_recovered' ? '恢复并计算' : '登记并计算' }}</el-button>
          </el-form>
          </el-collapse-item></el-collapse>
          <div v-if="hasCurrentAdjustment && (jobResult || jobRunning)" class="plan-action"><el-button class="full" :loading="jobRunning" @click="adjustOpen = true">{{ jobRunning ? '计算中，查看进度' : '查看调整方案' }}</el-button></div>

        </template>
        <div v-else class="operations-placeholder"><Tools /><h3>启用计划后可操作</h3></div>
      </aside>
    </div>

    <el-drawer v-model="adjustOpen" :title="store.historyView ? '历史计算记录' : '调整后续计划'" size="min(960px, 96vw)">
      <el-alert v-if="drawerJobRunning || generating" title="正在计算，可关闭窗口。" type="info" :closable="false" show-icon />
      <el-alert v-if="store.adjustment?.status === 'failed'" :title="store.adjustment.error" type="error" :closable="false" show-icon />
      <el-alert v-if="store.historyView" :title="store.adjustment?.trigger?.kind === 'baseline' ? '历史基线评估，未关联运维变化，仅供查看。' : '历史计算记录，仅供查看。'" type="info" :closable="false" show-icon />
      <el-alert v-else-if="store.stale" title="运行条件已变化或方案已应用，请重新计算。" type="warning" :closable="false" show-icon />
      <template v-if="jobResult">
        <div class="candidate-grid"><button v-for="(c, index) in jobResult.candidates" :key="c.id" class="candidate" :class="{ selected: selected?.id === c.id }" @click="selectedId = c.id"><span>{{ index === 0 ? '推荐方案' : `方案 ${index + 1}` }}<el-tag type="success" size="small">校验通过</el-tag></span><small class="candidate-caption">{{ commitmentSummary(c.metrics).unknownDue ? '预计完成' : '预计延期' }}</small><strong :class="{ 'completion-time': commitmentSummary(c.metrics).unknownDue }">{{ candidateHeadline(c.metrics) }}<small v-if="!commitmentSummary(c.metrics).unknownDue && !commitmentSummary(c.metrics).unknownCompletion">分钟</small></strong><p>{{ c.metrics.changed_tasks }} 项调整<span v-if="commitmentSummary(c.metrics).unknownDue"> · {{ commitmentSummary(c.metrics).unknownDue }} 单未设交期</span></p></button></div>
        <el-empty v-if="!jobResult.candidates.length" :description="jobResult.scope?.capacity_request ? '影响超过7天，需补充资源与远期计划。' : instance?.status === 'idle' ? '任务已全部完成，无需调整。' : '当前没有可行方案，请检查资源、物料和恢复时间。'" />
        <template v-if="selected"><div class="adjust-summary"><span>原安排 <b>{{ delayLabel(jobResult.baseline?.metrics) }}</b></span><span>调整后 <b>{{ delayLabel(selected.metrics) }}</b></span><span>覆盖未来 {{ selected.scope.hours }} 小时</span></div>
          <el-alert v-if="selectedCommitments.unknownDue" :title="`${selectedCommitments.unknownDue} 单未设承诺交期，暂不能判断是否延期；预计完成时间见下方。`" type="info" :closable="false" show-icon class="notice" />
          <el-collapse class="delivery-assessment"><el-collapse-item :title="selectedCommitments.unknownDue ? '查看预计完成 / 设置交期' : '查看交付时间'"><el-table :data="selected.metrics.orders || []" size="small" max-height="230"><el-table-column prop="name" label="订单" min-width="140" /><el-table-column label="预计完成" min-width="145"><template #default="{ row }">{{ fmt(row.completion_at, true) }}</template></el-table-column><el-table-column label="承诺交期" min-width="145"><template #default="{ row }">{{ row.due_at == null ? '未设置' : fmt(row.due_at, true) }}</template></el-table-column><el-table-column label="延期" width="120"><template #default="{ row }">{{ row.due_at == null ? '无法判断' : row.completion_at == null ? '完工待评估' : `${minutes(row.delay_seconds)} 分` }}</template></el-table-column><el-table-column width="90"><template #default="{ row }"><el-button link type="primary" @click="adjustOpen = false; openEvent('order_change', row.order_id, 'order')">设置交期</el-button></template></el-table-column></el-table></el-collapse-item></el-collapse>
          <el-alert v-if="selected.assumptions.length" title="部分安排依赖预计复机，实际开工仍需确认恢复。" type="warning" :closable="false" show-icon />
          <div class="panel-heading"><h2>调整明细</h2><el-checkbox v-model="onlyChanges">只看变化</el-checkbox></div>
          <el-table :data="candidateRows" size="small" max-height="420"><el-table-column prop="name" label="任务" min-width="180" /><el-table-column label="资源" width="100"><template #default="{ row }"><span v-if="row.oldResource !== row.resource_id" class="muted">{{ row.oldResource || '—' }} → </span>{{ row.resource_id }}</template></el-table-column><el-table-column label="原安排" min-width="150"><template #default="{ row }">{{ fmt(row.oldStart, true) }}</template></el-table-column><el-table-column label="新开始 — 结束" min-width="180"><template #default="{ row }">{{ fmt(row.start_at, true) }}—{{ fmt(row.end_at) }}</template></el-table-column><el-table-column label="路线" min-width="100"><template #default="{ row }">{{ row.from_node ? `${row.from_node} → ${row.to_node}` : '—' }}</template></el-table-column></el-table>
          <el-collapse class="details-collapse"><el-collapse-item :title="`校验与计算详情 · ${selected.validation.checked_count} 项通过`"><p>{{ selected.explanation }}</p><el-table :data="selected.validation.checks" size="small" max-height="260"><el-table-column prop="target" label="对象" width="130" /><el-table-column prop="message" label="检查" /><el-table-column prop="status" label="结果" width="100" /></el-table></el-collapse-item></el-collapse>
        </template>
        <el-collapse v-if="jobResult.failures?.length"><el-collapse-item title="不可行原因"><p v-for="(message, i) in adjustmentFailures" :key="i" class="muted">{{ message }}</p></el-collapse-item></el-collapse>
      </template>
      <template #footer><el-button v-if="store.historyView" @click="adjustOpen = false">关闭</el-button><template v-else><el-button :loading="generating || jobRunning" :disabled="!online || !needsAdjustment" @click="generate">重新计算</el-button><el-button type="primary" :disabled="!selected || store.stale || !selected.validation.passed || !online || generating || jobRunning" :loading="store.busy" @click="applySelected">应用此计划</el-button></template></template>
    </el-drawer>

    <el-drawer v-model="historyOpen" title="运行记录" size="min(850px, 96vw)"><el-tabs><el-tab-pane label="变化与执行"><el-table :data="store.history.events" size="small"><el-table-column label="时间" width="145"><template #default="{ row }">{{ fmt(row.occurred_at ?? row.at, true) }}</template></el-table-column><el-table-column label="事件" min-width="130"><template #default="{ row }">{{ eventLabel(row.type) }}</template></el-table-column><el-table-column prop="target_id" label="对象" width="140" /><el-table-column label="备注" min-width="160"><template #default="{ row }">{{ row.reason || '—' }}</template></el-table-column></el-table></el-tab-pane><el-tab-pane label="方案计算记录"><el-table :data="store.history.adjustments" size="small"><el-table-column label="时间" width="160"><template #default="{ row }">{{ fmt(row.created_at, true) }}</template></el-table-column><el-table-column label="状态" width="100"><template #default="{ row }">{{ { queued: '排队中', running: '计算中', done: row.applied_at ? '已应用' : '已计算', failed: '失败' }[row.status] }}</template></el-table-column><el-table-column label="来源" width="110"><template #default="{row}">{{row.trigger?.kind === 'event' ? `运维变化 #${row.trigger.event_seq}` : '基线评估'}}</template></el-table-column><el-table-column label="操作"><template #default="{ row }"><el-button link type="primary" @click="store.watchAdjustment(row.id, {history:true}); selectedId = ''; historyOpen = false; adjustOpen = true">查看记录</el-button></template></el-table-column></el-table></el-tab-pane><el-tab-pane label="往轮案例"><el-table :data="store.archives" size="small"><el-table-column prop="name" label="案例" /><el-table-column label="归档时间"><template #default="{row}">{{ fmt(row.archived_at, true) }}</template></el-table-column><el-table-column label="完成"><template #default="{row}">{{row.completed}}/{{row.tasks}}</template></el-table-column><el-table-column prop="reason" label="说明" /><el-table-column label="记录"><template #default="{row}"><el-button link type="primary" @click="viewArchive(row)">查看上一轮</el-button></template></el-table-column></el-table></el-tab-pane></el-tabs></el-drawer>
    <el-drawer v-model="bucketOpen" :title="bucketTitle" size="min(900px, 96vw)"><el-table :data="bucketTasks" size="small" empty-text="该时段没有已导入任务"><el-table-column prop="name" label="任务" min-width="180" /><el-table-column prop="resource_id" label="资源" width="80" /><el-table-column label="开始" min-width="145"><template #default="{ row }">{{ fmt(row.start_at, true) }}</template></el-table-column><el-table-column label="结束" min-width="145"><template #default="{ row }">{{ fmt(row.end_at, true) }}</template></el-table-column><el-table-column label="操作" width="100"><template #default="{ row }"><el-button link type="primary" :disabled="row.status === 'completed'" @click="bucketOpen = false; openTaskEvent(row)">调整参数</el-button></template></el-table-column></el-table><p v-if="bucketSupplyCount" class="muted">本时段另有 {{ bucketSupplyCount }} 批到货，可在物料环节调整。</p></el-drawer>

    <el-dialog v-model="archiveOpen" title="往轮执行记录" width="min(850px, 94vw)"><el-table :data="archiveEvents" size="small" max-height="480"><el-table-column label="时间"><template #default="{row}">{{ fmt(row.occurred_at ?? row.at, true) }}</template></el-table-column><el-table-column label="事件"><template #default="{row}">{{eventLabel(row.type)}}</template></el-table-column><el-table-column prop="target_id" label="对象" /><el-table-column prop="reason" label="备注" /></el-table></el-dialog>
    <ChainPlanDialog v-model="chainOpen" :example-case="String(route.query.example || '')" :history-record="String(route.query.history_record || '')" :history-module="String(route.query.history_module || '')" />
    <el-dialog v-model="manageOpen" :title="planSource === 'production' ? '生产计划同步' : '计划设置'" width="min(700px, 94vw)">
      <div v-if="instance" class="current-plan"><b>{{ instance.plan.name }}</b><span>修订 {{ instance.plan_revision }} · {{ fmt(instance.plan.start_at, true) }} 启用</span><el-tag size="small" :type="instance.status === 'idle' ? 'info' : 'success'">{{ instance.status === 'idle' ? '已完成' : '执行中' }}</el-tag></div>
      <el-alert v-if="instance && planSource === 'production'" title="同步保留进度；切换计划将归档本轮。" type="info" :closable="false" />
      <el-form label-position="top" class="plan-form">
        <el-form-item label="计划来源"><el-radio-group v-model="planSource"><el-radio-button value="production">库内已排程计划</el-radio-button><el-radio-button value="standard">演示基线（备用）</el-radio-button><el-radio-button value="custom">导入 JSON</el-radio-button></el-radio-group></el-form-item>
        <p v-if="planSource === 'standard'" class="muted">冰箱生产 → 组装 → 配送，可在预览中核对来源。</p>
        <template v-if="planSource === 'production'">
          <el-form-item label="原生产计划"><el-select v-model="productionId" filterable class="full" :loading="loadingSources" placeholder="选择原系统已保存计划"><el-option v-for="p in productionSources" :key="p.id" :value="p.id" :label="`${p.name} · ${p.job_count}工单`" :disabled="!p.can_preview" /></el-select></el-form-item>
          <el-form-item label="排程结果"><el-select v-model="productionSolver" class="full"><el-option v-for="s in selectedSource?.solvers || []" :key="s" :value="s" :label="s.toUpperCase()" /></el-select></el-form-item>
          <el-form-item label="原计划时间单位"><el-select v-model="productionTimeUnit" class="full"><el-option value="hours" label="小时（原生产界面口径）" /><el-option value="minutes" label="分钟" /><el-option value="seconds" label="秒" /></el-select></el-form-item>
        </template>
        <el-form-item v-if="planSource === 'custom'" label="完整统一计划"><el-input v-model="planJson" type="textarea" :rows="8" /></el-form-item>
        <el-collapse><el-collapse-item title="生效时间 / 历史回放"><el-form-item v-if="planSource !== 'custom'" :label="planSource === 'production' && instance ? '北京时间（留空保留原计划日期；新运行从当前时间开始）' : '北京时间（留空从当前时间开始）'"><input type="datetime-local" v-model="planStart" class="date-input" /></el-form-item><el-checkbox v-model="allowReplay">允许模拟历史回放</el-checkbox></el-collapse-item></el-collapse>
      </el-form>
      <div v-if="preview" class="preview-box"><b>{{ !preview.can_activate ? '暂不能同步' : preview.mode === 'sync' ? '可以同步' : preview.requires_new_run ? '可以启用为新运行' : '校验通过' }}</b><p v-if="preview.message">{{ preview.message }}</p><p v-if="preview.summary">更新 {{ preview.summary.updated_count }} 项参数 · 保留 {{ preview.summary.retained_count }} 项已执行事实</p><p v-for="gap in preview.gaps || []" :key="gap">{{ gap }}</p><p v-for="(v, i) in preview.validation?.violations?.slice(0, 4) || []" :key="i">{{ v.target }}：{{ v.message }}</p><small v-if="preview.can_activate">{{ preview.plan.tasks.length }} 项任务</small></div>
      <el-collapse v-if="preview?.plan || instance" class="source-details"><el-collapse-item title="来源与关联"><div v-for="(s, index) in (preview?.plan || instance?.plan)?.source_manifest || []" :key="index" class="source-row"><b>{{ { production: '原生产计划', assembly: '原组装定义', material: '原物料目录', logistics: '原物流路线', binding: '标准关联参数' }[s.module] || s.module }}</b><span>{{ s.id || s.path || s.paths?.join('、') }}</span><small v-if="s.solver">算法 {{ s.solver }} · 单位 {{ s.time_unit }}</small><small v-if="s.vehicle_id != null">车辆 {{ s.vehicle_id }} · 路线 {{ s.route_id }}</small></div><p v-for="a in (preview?.plan || instance?.plan)?.baseline_parameters || []" :key="a" class="muted">{{ a }}</p></el-collapse-item></el-collapse>
      <template #footer><el-button :loading="managing" @click="previewPlan">{{ planSource === 'production' && instance ? '预览同步' : '预览校验' }}</el-button><el-button type="primary" :loading="store.busy" :disabled="!canCommitPlan" @click="activatePlan">{{ preview?.mode === 'sync' ? '同步生产计划' : preview?.requires_new_run ? '归档当前运行并启用' : instance ? '归档并启用新计划' : '启用所选计划' }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Calendar, Connection, ArrowDown, SetUp, Box, Van, Tools } from '@element-plus/icons-vue'
import { useOperationsStore } from '../stores/useOperationsStore'
import { api } from '../api/client'
import OperationsTimeline from '../components/operations/OperationsTimeline.vue'
import { liveTimelineWindow } from '../utils/timelineNavigation'
import { useRoute } from 'vue-router'
import ChainPlanDialog from '../components/operations/ChainPlanDialog.vue'
import { hasPendingOperationsChange, isCurrentOperationsAdjustment, aggregatePlan, commitmentSummary, inStage, planRows, planWindow, visiblePlanRows } from '../utils/operationsPlan'

const store = useOperationsStore()
const instance = computed(() => store.instance)
const legacyBaseline = computed(() => instance.value?.plan.id === 'REFRIGERATOR-STANDARD-v1')
const businessOrders = computed(() => instance.value?.plan.orders.filter((o) => o.role !== 'component') || [])
const online = computed(() => store.connected && ['online', 'follower'].includes(store.payload?.health?.status))
const stage = ref('all'), hours = ref(4), domain = ref('production')
const resourcesExpanded = ref(false)
const stageNames = { production: '生产', material: '物料', assembly: '组装', delivery: '配送' }
const domains = { ...stageNames, order: '订单承诺' }
const kinds = { transport: '入厂运输', production: '生产', assembly: '组装', loading: '装车', delivery: '配送', return: '返场' }
const grains = [{ hours: 4, label: '实时 · 4h' }, { hours: 24, label: '今日' }, { hours: 168, label: '7天' }, { hours: 672, label: '4周' }]
const actions = {
  production: [{ type: 'resource_unavailable', label: '机台故障' }, { type: 'duration_change', label: '调整工时' }, { type: 'resource_recovered', label: '确认恢复' }, { type: 'release_change', label: '开工时间' }],
  material: [{ type: 'supply_delay', label: '备货/到货时间' }, { type: 'supply_quantity', label: '到货数量' }, { type: 'inventory_count', label: '库存修正' }],
  assembly: [{ type: 'resource_unavailable', label: '工位停用' }, { type: 'duration_change', label: '调整工时' }, { type: 'resource_recovered', label: '确认恢复' }, { type: 'release_change', label: '开工时间' }],
  delivery: [{ type: 'duration_change', label: '入厂运输耗时' }, { type: 'resource_unavailable', label: '车辆缺失' }, { type: 'travel_change', label: '路段耗时' }, { type: 'resource_recovered', label: '确认恢复' }, { type: 'window_change', label: '收货窗口' }, { type: 'service_change', label: '卸货耗时' }, { type: 'release_change', label: '发车时间' }],
  order: [{ type: 'order_change', label: '承诺与优先级' }],
}
const operationsPanel = ref(null), targetSelect = ref(null), manualSections = ref([])
const route = useRoute() || {query:{}}
const chainOpen = ref(false)
watch(() => [route.query.example,route.query.history_record], values => { if (values.some(Boolean)) chainOpen.value = true })
const archiveEvents = ref([]), archiveOpen = ref(false)
async function viewArchive(run) { try { archiveEvents.value = (await api.get(`/api/operations-tools/cases/archives/${run.run_id}/history`)).data.events; archiveOpen.value = true } catch(e) { fail(e) } }
async function reloadCase() { try { await ElMessageBox.confirm('归档本轮记录，按原案例从当前时间重新开始？', '重新加载模拟案例', { confirmButtonText: '重新开始', cancelButtonText: '返回' }); const result = await store.reloadCase(); if (result.status === 'done') ElMessage.success('新一轮模拟已开始') } catch(e) { if (e !== 'cancel' && e !== 'close') fail(e) } }
const adjustOpen = ref(false), historyOpen = ref(false), manageOpen = ref(false), pendingAdjustment = ref(false), generating = ref(false)
watch(historyOpen, open => { if (open) store.loadArchives().catch(fail) })
const needsAdjustment = computed(() => hasPendingOperationsChange(instance.value))
watch(() => instance.value?.run_id, () => { assistantResult.value=null; manualSections.value=[]; pendingAdjustment.value = false; domain.value = 'production'; stage.value = 'all'; form.type = 'resource_unavailable'; form.target_id = ''; form.resource_id = ''; form.scheduled = false; selectedId.value = ''; adjustOpen.value = false; bucketOpen.value = false; preview.value = null })
const fmt = (n, date = false) => n == null ? '—' : new Date(typeof n === 'number' ? n * 1000 : n).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', ...(date ? { month: '2-digit', day: '2-digit' } : {}), hour: '2-digit', minute: '2-digit' })
const dayLabel = (n) => new Date(n * 1000).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit' })
const minutes = (n) => (Number(n || 0) / 60).toFixed(1)
const clockTime = computed(() => new Date(store.now * 1000).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }))
const manualWindow = ref(null)
const followingCurrent = computed(() => !manualWindow.value)
const viewWindow = computed(() => manualWindow.value || (hours.value === 4 ? liveTimelineWindow(store.now, 4) : planWindow(store.now, hours.value)))
function navigateTimeline(window) { manualWindow.value = {...window} }
function resumeTimeline() { manualWindow.value = null }
watch(hours, value => { if (manualWindow.value) { const range=manualWindow.value; manualWindow.value=liveTimelineWindow(range.begin+(range.end-range.begin)*.2,value) } })
watch(() => instance.value?.run_id, resumeTimeline)
watch(() => instance.value?.constraint_version, () => {assistantResult.value=null})
const rangeLabel = computed(() => hours.value === 4 ? `${fmt(viewWindow.value.begin)}—${fmt(viewWindow.value.end)}` : `${dayLabel(viewWindow.value.begin)}—${dayLabel(viewWindow.value.end - 1)}`)
const rows = computed(() => planRows(instance.value))
const visibleTasks = computed(() => visiblePlanRows(instance.value, viewWindow.value, stage.value, hours.value === 4 && followingCurrent.value ? store.now : null))
const windowSupplies = computed(() => instance.value?.plan.supplies.filter((s) => s.available_at >= viewWindow.value.begin && s.available_at < viewWindow.value.end) || [])
const buckets = computed(() => aggregatePlan(instance.value, viewWindow.value, hours.value, stage.value))
const scheduleMap = computed(() => Object.fromEntries((instance.value?.schedule || []).map((s) => [s.task_id, s])))
const currentCommitments = computed(() => commitmentSummary(instance.value?.metrics))
const completed = computed(() => instance.value?.tasks.filter((t) => t.status === 'completed').length || 0)
const delivered = computed(() => businessOrders.value.filter((o) => { const tasks = o.fulfillment_stage === 'production' ? instance.value.tasks.filter((t) => o.completion_task_ids.includes(t.id)) : instance.value.tasks.filter((t) => t.kind === 'delivery' && t.order_id === o.id); return tasks.length && tasks.every((t) => t.status === 'completed') }).length)
const visibleResources = computed(() => instance.value?.resources.filter((r) => inStage(r.kind === 'vehicle' ? 'delivery' : r.kind, stage.value)) || [])
const stages = computed(() => Object.keys(stageNames).map((id) => {
  const tasks = id === 'material' ? instance.value?.plan.supplies || [] : instance.value?.tasks.filter((t) => inStage(t.kind, id)) || []
  const done = id === 'material' ? instance.value?.received_supplies.length || 0 : tasks.filter((t) => t.status === 'completed').length
  const resources = instance.value?.resources.filter((r) => (id === 'delivery' ? r.kind === 'vehicle' : r.kind === id) && !r.available).length || 0
  return { id, name: stageNames[id], done, total: tasks.length, running: id === 'material' ? tasks.length - done : tasks.filter((t) => t.status === 'running').length,
    issues: resources || tasks.filter((t) => t.status === 'paused' || t.blocked_reason).length,
    icon: { production: SetUp, material: Box, assembly: Connection, delivery: Van }[id], color: { production: '#497ce2', material: '#9b78cc', assembly: '#23a18b', delivery: '#d49a42' }[id] }
}))
function selectStage(id) { stage.value = stage.value === id ? 'all' : id; domain.value = id }
const unavailableResources = computed(() => visibleResources.value.filter(r => !r.available))
function handleMenu(command) { if (command === 'source') openProductionSource(); else if (command === 'reload') reloadCase(); else if (command === 'history') historyOpen.value = true; else if (command === 'refresh') refreshAll() }
function resourceWork(rid) { return instance.value?.tasks.find((t) => t.resource_id === rid && ['running', 'paused'].includes(t.status))?.name || '当前空闲' }
function resourceName(id) { return instance.value?.resources.find((r) => r.id === id)?.name || id }
function inventoryLabel(key) { const [location, material] = key.split('|'); const stock = instance.value?.plan.stock.find((s) => s.material_id === material && s.location === location); const output = instance.value?.plan.tasks.flatMap((t) => t.outputs || []).find((s) => s.material_id === material); return stock?.name || output?.name || material }
function statusName(t) { return { pending: t.blocked_reason ? '等待条件' : '待开工', running: '执行中', paused: '中断', completed: '已完成' }[t.status] || t.status }
function statusTone(t) { return t.status === 'completed' ? 'success' : t.status === 'paused' || t.blocked_reason ? 'warning' : t.status === 'running' ? 'primary' : 'info' }
function eventLabel(type) { return store.payload?.parameters?.find((p) => p.type === type)?.label || ({ task_started: '任务开始', task_completed: '任务完成', task_paused: '任务中断', supply_received: '供给收到', case_reloaded: '重新加载案例', plan_activated: '计划启用', adjustment_applied: '应用调整', production_source_synced: '生产来源同步' }[type] || type) }
function fail(e) { const detail = e.response?.data?.detail || e.message || String(e); ElMessage.error(typeof detail === 'string' ? detail : JSON.stringify(detail)) }
async function refreshAll() { try { await store.refresh(); await store.loadHistory(); await store.refreshProductionSource() } catch (e) { fail(e) } }

const bucketOpen = ref(false), selectedBucket = ref(null)
const bucketTitle = computed(() => selectedBucket.value ? `${dayLabel(selectedBucket.value.start)}—${dayLabel(selectedBucket.value.end - 1)} 计划明细` : '计划明细')
const bucketTasks = computed(() => selectedBucket.value ? rows.value.filter((t) => inStage(t.kind, stage.value) && t.start_at < selectedBucket.value.end && t.end_at > selectedBucket.value.start) : [])
const bucketSupplyCount = computed(() => selectedBucket.value ? instance.value?.plan.supplies.filter((s) => s.available_at >= selectedBucket.value.start && s.available_at < selectedBucket.value.end).length : 0)
function drillBucket(bucket) { selectedBucket.value = bucket; bucketOpen.value = true }

const hasCurrentAdjustment=computed(()=>!store.historyView && isCurrentOperationsAdjustment(store.adjustment,instance.value))
const jobRunning = computed(() => hasCurrentAdjustment.value && ['queued', 'running'].includes(store.adjustment?.status))
const drawerJobRunning=computed(()=>['queued','running'].includes(store.adjustment?.status))
const jobResult = computed(() => store.adjustment?.result)
const adjustmentFailures = computed(() => [...new Set((jobResult.value?.failures || []).map((f) => f.message).filter(Boolean))].slice(0, 8))
const selectedId = ref(''), onlyChanges = ref(true)
watch(adjustOpen,(open,old)=>{if(!open && old && store.historyView)store.restoreCurrentAdjustment?.()})
const selected = computed(() => jobResult.value?.candidates?.find((c) => c.id === selectedId.value) || jobResult.value?.candidates?.[0])
const selectedCommitments = computed(() => commitmentSummary(selected.value?.metrics))
function candidateHeadline(metrics) { const summary = commitmentSummary(metrics); return summary.unknownCompletion ? '完工待评估' : summary.unknownDue ? fmt(summary.completionAt, true) : minutes(summary.delaySeconds) }
function delayLabel(metrics) { if (!metrics) return '待评估'; const summary = commitmentSummary(metrics); return summary.unknownDue ? `${summary.unknownDue} 单未设交期` : summary.unknownCompletion ? '完工待评估' : `延期 ${minutes(summary.delaySeconds)} 分` }
const candidateRows = computed(() => (selected.value?.schedule || []).map((s) => { const old = scheduleMap.value[s.task_id]; return { ...s, name: instance.value?.tasks.find((t) => t.id === s.task_id)?.name || s.task_id, oldResource: old?.resource_id, oldStart: old?.start_at, changed: !old || old.resource_id !== s.resource_id || Math.abs(old.start_at - s.start_at) > 1 || Math.abs(old.end_at - s.end_at) > 1 } }).filter((s) => !onlyChanges.value || s.changed).sort((a, b) => a.start_at - b.start_at))
async function generate() { if(!needsAdjustment.value){ElMessage.info('当前没有待处理的运维变化，无需调整');return} adjustOpen.value = true; if (jobRunning.value || generating.value) return; generating.value = true; selectedId.value = ''; try { await store.generate() } catch (e) { fail(e) } finally { generating.value = false } }
async function applySelected() { if(store.historyView || !hasCurrentAdjustment.value){ElMessage.info('请使用当前变化对应的调整方案');return} try { await ElMessageBox.confirm(`应用后调整 ${selected.value.metrics.changed_tasks} 项安排，正在执行的进度保留。`, '应用此计划', { confirmButtonText: '确认应用', cancelButtonText: '返回' }); const result = await store.apply(selected.value); if (result.status === 'done') { pendingAdjustment.value = false; adjustOpen.value = false; ElMessage.success('新计划已应用') } else ElMessage.info('正在提交，请在记录中查看结果') } catch (e) { if (e !== 'cancel' && e !== 'close') fail(e) } }

const localDate = (sec) => new Date(sec * 1000 + 8 * 3600000).toISOString().slice(0, 16)
const parseDate = (s) => { if (!s) throw new Error('请填写北京时间'); return new Date(`${s}+08:00`).toISOString() }
const form = reactive({ type: 'resource_unavailable', target_id: '', resource_id: '', value: 1, at: '', until: '', priority: 1, knownRecovery: true, recoveryMinutes: 20, scheduled: false, scheduledAt: '', source: 'manual_simulation', reason: '', operator: '本地操作员' })
const targetType = computed(() => store.payload?.parameters?.find((p) => p.type === form.type)?.target)
const targetLabel = computed(() => ({ resource: domain.value === 'delivery' ? '车辆' : domain.value === 'assembly' ? '组装工位' : '机台', task: domain.value === 'delivery' ? '配送任务' : '产品工序', supply: '供给批次', stock: '物料 / 库位', road: '路段', order: '订单' }[targetType.value] || '具体对象'))
const targets = computed(() => {
  if (!instance.value) return []
  const st = instance.value
  if (targetType.value === 'resource') return st.resources.filter((r) => r.kind === (domain.value === 'delivery' ? 'vehicle' : domain.value) && (form.type !== 'resource_recovered' || !r.available)).map((r) => ({ id: r.id, label: r.name }))
  if (targetType.value === 'task') return st.tasks.filter((t) => t.status !== 'completed' && (form.type === 'duration_change' || t.status === 'pending') && (domain.value === 'delivery' ? (form.type === 'duration_change' ? t.kind === 'transport' : ['transport','delivery'].includes(t.kind)) : t.kind === domain.value)).map((t) => ({ id: t.id, label: t.name }))
  if (targetType.value === 'supply') return st.plan.supplies.filter((s) => !st.received_supplies.includes(s.id)).map((s) => ({ id: s.id, label: `${s.id} · ${s.name || s.material_id}` }))
  if (targetType.value === 'stock') return Object.keys(st.inventory).map((id) => ({ id, label: inventoryLabel(id) }))
  if (targetType.value === 'road') return Object.keys(st.plan.travel_seconds).map((id) => ({ id, label: id.replace('|', ' → ') }))
  if (targetType.value === 'order') return st.plan.orders.map((o) => ({ id: o.id, label: `${o.id} · ${o.name}` }))
  return []
})
const targetTask = computed(() => instance.value?.tasks.find((t) => t.id === form.target_id))
const originalValue = computed(() => {
  const st = instance.value
  if (!st || !form.target_id) return ''
  if (form.type === 'resource_unavailable' || form.type === 'resource_recovered') return st.resources.find((r) => r.id === form.target_id)?.available ? '可用' : '不可用'
  if (form.type === 'duration_change') { const a = targetTask.value?.alternatives.find((a) => a.resource_id === form.resource_id); return a ? `${minutes(a.unit_seconds ?? a.duration_seconds)} 分钟/${targetTask.value.duration_mode === 'per_unit' ? '件' : '批次'}` : '' }
  if (form.type === 'travel_change') return `${minutes(st.plan.travel_seconds[form.target_id])} 分钟`
  if (form.type === 'service_change') return `${minutes(targetTask.value?.service_seconds)} 分钟`
  if (form.type === 'inventory_count') return String(st.inventory[form.target_id])
  if (form.type.startsWith('supply')) { const s = st.plan.supplies.find((s) => s.id === form.target_id); return s ? `${s.quantity} 件 · ${fmt(s.available_at, true)}` : '' }
  return ''
})
function actionEnabled(type) { if (!instance.value) return false; if (type.startsWith('supply')) return instance.value.plan.supplies.some((s) => !instance.value.received_supplies.includes(s.id)); if (type === 'resource_recovered') return instance.value.resources.some((r) => r.kind === (domain.value === 'delivery' ? 'vehicle' : domain.value) && !r.available); return true }
watch(domain, () => { form.type = actions[domain.value].find((a) => actionEnabled(a.type))?.type || actions[domain.value][0].type; form.target_id = '' }, { flush: 'sync' })
watch(() => form.type, () => { form.target_id = ''; form.resource_id = ''; form.at = localDate(store.now + 1200); form.until = localDate(store.now + 10800) }, { flush: 'sync' })
watch(() => form.target_id, () => {
  if (targetTask.value) { const t = targetTask.value; form.resource_id = t.resource_id || scheduleMap.value[t.id]?.resource_id || t.alternatives[0].resource_id; if (form.type === 'service_change') form.value = (t.service_seconds || 0) / 60 }
  if (form.type === 'travel_change') form.value = instance.value?.plan.travel_seconds[form.target_id] / 60
  if (form.type === 'inventory_count') form.value = instance.value?.inventory[form.target_id]
  if (form.type.startsWith('supply')) { const s = instance.value?.plan.supplies.find((s) => s.id === form.target_id); if (s) { form.at = localDate(s.available_at); form.value = s.quantity } }
  if (form.type === 'order_change') { const o = instance.value?.plan.orders.find((o) => o.id === form.target_id); if (o) { form.at = localDate(o.due_at ?? store.now + 86400); form.priority = o.priority } }
  if (form.type === 'release_change' && targetTask.value) form.at = localDate(Math.max(store.now, targetTask.value.release_at))
  if (form.type === 'window_change' && targetTask.value) { form.at = localDate(targetTask.value.window_start ?? store.now); form.until = localDate(targetTask.value.window_end ?? store.now + 7200) }
}, { flush: 'sync' })
watch([() => form.target_id, () => form.resource_id], () => { if (form.type !== 'duration_change') return; const a = targetTask.value?.alternatives.find((a) => a.resource_id === form.resource_id); if (a) form.value = (a.unit_seconds ?? a.duration_seconds) / 60 }, { flush: 'sync' })
async function focusOperations() { await nextTick(); const panel = operationsPanel.value; if (panel && (panel.getBoundingClientRect().top < 0 || panel.getBoundingClientRect().bottom > window.innerHeight)) panel.scrollIntoView({ behavior: 'smooth', block: 'start' }); targetSelect.value?.focus() }
function openEvent(type, target, selectedDomain) { manualSections.value=['parameters']; const r = instance.value?.resources.find((r) => r.id === target); if (selectedDomain) domain.value = selectedDomain; else if (r) domain.value = r.kind === 'vehicle' ? 'delivery' : r.kind; form.type = type; form.target_id = target || ''; form.knownRecovery = true; form.recoveryMinutes = 20; form.scheduled = false; form.scheduledAt = localDate(store.now + 300); form.reason = ''; focusOperations() }
function openTaskEvent(t) { const d = ['transport', 'loading', 'delivery', 'return'].includes(t.kind) ? 'delivery' : t.kind; if (t.status === 'completed') return; const resource = t.resource_id || scheduleMap.value[t.id]?.resource_id; if (['loading', 'return'].includes(t.kind)) openEvent('resource_unavailable', resource, d); else if (t.kind === 'delivery' && t.status !== 'pending') openEvent('resource_unavailable', resource, d); else openEvent(t.kind === 'delivery' ? 'service_change' : 'duration_change', t.id, d) }
async function submitEvent() {
  if (!form.target_id) return
  try {
    let data = {}; const t = form.type
    if (t === 'resource_unavailable' && form.knownRecovery && (!Number.isFinite(form.recoveryMinutes) || form.recoveryMinutes < 1)) throw new Error('请填写有效的预计恢复时长')
    if (['duration_change','service_change','travel_change','supply_quantity','inventory_count'].includes(t) && (!Number.isFinite(form.value) || form.value < 0 || (['duration_change','travel_change'].includes(t) && form.value === 0))) throw new Error('请填写有效的新参数')
    const effectiveAt = form.scheduled ? new Date(parseDate(form.scheduledAt)).getTime() / 1000 : store.now
    if (t === 'resource_unavailable') data.expected_recovery_at = form.knownRecovery ? effectiveAt + form.recoveryMinutes * 60 : null
    if (t === 'duration_change') data = { duration_mode: targetTask.value.duration_mode, resource_id: form.resource_id, value: form.value * 60 }
    if (['service_change','travel_change'].includes(t)) data.seconds = form.value * 60
    if (t === 'travel_change') { const [from_node, to_node] = form.target_id.split('|'); Object.assign(data, { from_node, to_node }) }
    if (t === 'inventory_count') { const [location, material_id] = form.target_id.split('|'); data = { location, material_id, quantity: form.value } }
    if (t === 'supply_quantity') data.quantity = form.value
    if (t === 'supply_delay') data.available_at = parseDate(form.at)
    if (t === 'release_change') data.release_at = parseDate(form.at)
    if (t === 'window_change') data = { window_start: parseDate(form.at), window_end: parseDate(form.until) }
    if (t === 'order_change') data = { due_at: parseDate(form.at), priority: form.priority }
    const scheduled = form.scheduled, submittedRun = instance.value.run_id
    const result = await store.event({ type: t, target_id: form.target_id, data, source: form.source, reason: form.reason, operator: form.operator, ...(scheduled ? { scheduled_at: parseDate(form.scheduledAt) } : {}) })
    if (submittedRun !== instance.value?.run_id) { ElMessage.info('当前案例已切换，请在记录中查看提交结果'); return }
    if (result.status === 'done' && !scheduled) {
      pendingAdjustment.value = true
      if (t === 'resource_recovered') form.type = 'resource_unavailable'
      if (jobRunning.value) ElMessage.success('变化已登记，当前计算结束后请重新计算')
      else { ElMessage.success('变化已登记，正在计算'); await generate() }
    }
    else if (result.status === 'done') ElMessage.success('变化已预约')
    else ElMessage.info(scheduled ? '变化已预约' : '正在提交，请在记录中确认结果')
  } catch (e) { fail(e) }
}

const question = ref(''), asking = ref(false), assistantResult = ref(null)
const agentStatus = computed(() => {
  if(asking.value)return '分析中'
  if(jobRunning.value || (needsAdjustment.value && assistantResult.value?.adjustment_id && store.adjustment?.id!==assistantResult.value.adjustment_id))return '计算中'
  if(hasCurrentAdjustment.value && store.stale && jobResult.value)return '待重算'
  if(hasCurrentAdjustment.value && store.adjustment?.status==='failed')return '计算失败'
  if(assistantResult.value?.status==='failed')return '待重试'
  if(assistantResult.value?.prepared_event?.draft)return '待核对'
  if(assistantResult.value?.status==='needs_information')return '待补充'
  if(hasCurrentAdjustment.value && jobResult.value)return jobResult.value.candidates?.some(c=>c.validation?.passed) ? '方案待选' : '无可行方案'
  return assistantResult.value ? '已分析' : '就绪'
})
const agentSteps = computed(() => {
  const labels={'operations.query_state':'读取运行状态','operations.analyze_impact':'核对影响范围','operations.prepare_event':'识别变化参数','operations.propose_adjustment':'准备候选计算','llm.answer':'大模型问答'}
  const steps=(assistantResult.value?.trace || []).map(t=>({label:labels[t.tool] || '业务工具核验',status:t.ok ? '完成' : '失败'}))
  if(needsAdjustment.value && assistantResult.value?.adjustment_id){
    const job=store.adjustment?.id===assistantResult.value.adjustment_id ? store.adjustment : null
    const candidates=job?.result?.candidates || []
    steps.push({label:'候选方案与校验',status:!job || ['queued','running'].includes(job.status) ? '计算中' : job.status==='failed' ? '计算失败' : candidates.some(c=>c.validation?.passed) ? '有可行方案' : '无可行方案'})
  }
  return steps
})
function onAgentKeydown(event) {
  if(event.key==='Enter' && !event.shiftKey && !event.isComposing && event.keyCode!==229){event.preventDefault();return askAssistant()}
}
async function askAssistant(message) {
  if(typeof message==='string')question.value=message
  if(!question.value.trim() || asking.value || !instance.value)return
  const run=instance.value.run_id,version=instance.value.constraint_version
  asking.value=true
  assistantResult.value=null
  try{
    const result=(await api.post('/api/operations-tools/agent/run',{message:question.value,run_id:run,constraint_version:version,use_llm:true},{timeout:45000})).data
    if(run!==instance.value?.run_id || version!==instance.value?.constraint_version){ElMessage.info('运行状态已变化，请重新分析');return}
    assistantResult.value=result
    const d=result.prepared_event?.draft
    if(d){
      const task=instance.value.tasks.find(t=>t.id===d.target_id)
      openEvent(d.type,d.target_id,task?task.kind:d.type.startsWith('supply')?'material':undefined)
      form.reason=d.reason
      if(d.data.resource_id)form.resource_id=d.data.resource_id
      if(d.data.value!=null)form.value=d.data.value/60
      if(d.type==='resource_unavailable'){form.knownRecovery=d.data.expected_recovery_at!=null;form.recoveryMinutes=d.data.expected_recovery_at?Math.max(1,Math.ceil((d.data.expected_recovery_at-store.now)/60)):20}
      if(d.data.available_at)form.at=localDate(d.data.available_at)
    }
    if(result.adjustment_id && needsAdjustment.value){store.watchAdjustment(result.adjustment_id);adjustOpen.value=true}
  }catch(e){
    if(run===instance.value?.run_id && version===instance.value?.constraint_version){
      const detail=e.response?.data?.detail
      assistantResult.value={status:'failed',summary:e.code==='ECONNABORTED' ? '回答等待超时，请重试；当前运行继续。' : typeof detail==='string' ? detail : '暂时无法取得回答，请检查后端连接后重试。',llm_used:false}
    }
  }finally{asking.value=false}
}

const planSource = ref('production'), planStart = ref(''), productionId = ref(''), productionSolver = ref(''), planJson = ref(''), preview = ref(null), managing = ref(false), allowReplay = ref(false)
const productionSources = ref([]), loadingSources = ref(false), productionTimeUnit = ref('hours')
const selectedSource = computed(() => productionSources.value.find((p) => p.id === productionId.value))
watch(productionId, () => { productionSolver.value = selectedSource.value?.recommended_solver || selectedSource.value?.solvers[0] || '' }, { flush: 'sync' })
let sourcesRequest = null
function loadProductionSources() { if (sourcesRequest) return sourcesRequest; loadingSources.value = true; sourcesRequest = (async () => { try { productionSources.value = (await api.get('/api/operations-tools/plans/sources')).data.plans; if (!productionId.value) productionId.value = store.productionSource?.plan_id || ''; const source = selectedSource.value; if (!source?.solvers.includes(productionSolver.value)) productionSolver.value = source?.solvers.includes(source.recommended_solver) ? source.recommended_solver : source?.solvers[0] || '' } catch (e) { fail(e) } finally { loadingSources.value = false; sourcesRequest = null } })(); return sourcesRequest }
watch(manageOpen, (open) => { if (open) loadProductionSources() })
watch([planSource, planStart, productionId, productionSolver, productionTimeUnit, planJson], () => { preview.value = null }, { flush: 'sync' })
function planBody() { return { source: planSource.value, ...(planStart.value ? { start_at: parseDate(planStart.value) } : {}), ...(planSource.value === 'custom' ? { plan: JSON.parse(planJson.value) } : {}), ...(planSource.value === 'production' ? { plan_id: productionId.value, solver_id: productionSolver.value, time_unit: productionTimeUnit.value, source_version: preview.value?.source_version } : {}) } }
const canCommitPlan = computed(() => planSource.value === 'production' ? !!preview.value?.can_activate : !instance.value || instance.value.status === 'idle' || legacyBaseline.value)
function openProductionSource() { planSource.value = 'production'; const linked = store.productionSource; if (linked?.plan_id) { productionId.value = linked.plan_id; productionSolver.value = linked.solver_id; productionTimeUnit.value = linked.time_unit || 'hours' } manageOpen.value = true }
async function previewLinkedSource() { openProductionSource(); await loadProductionSources(); const linked = await store.refreshProductionSource(); if (linked?.plan_id) { productionId.value = linked.plan_id; productionSolver.value = linked.solver_id; productionTimeUnit.value = linked.time_unit || 'hours'; await nextTick(); await previewPlan() } }
async function previewPlan() { managing.value = true; try { const body = planBody(); delete body.source_version; const path = planSource.value === 'production' && instance.value ? '/api/operations-tools/plans/production/preview-sync' : '/api/operations-tools/plans/preview'; if (instance.value) body.run_id = instance.value.run_id; preview.value = (await api.post(path, body)).data } catch (e) { preview.value = null; fail(e) } finally { managing.value = false } }
async function activatePlan() {
  try {
    if (planSource.value === 'production' && preview.value?.mode === 'sync') {
      await ElMessageBox.confirm('同步库内排程的未开工部分，保留已执行进度与本地确认修改。', '同步生产计划', { confirmButtonText: '确认同步', cancelButtonText: '返回' })
      const result = await store.syncProduction(preview.value.preview_id)
      if (result.status === 'done') { manageOpen.value = false; form.target_id = ''; ElMessage.success('生产计划已同步') } else ElMessage.info('同步提交中，请在记录中查看结果')
      return
    }
    const body = planBody()
    if (instance.value) {
      await ElMessageBox.confirm(preview.value?.requires_new_run ? '所选计划属于新的运行批次。当前进度与事件将完整归档，新计划按当前时钟启用。' : '归档当前运行并启用所选计划？', '启用新运行')
      body.archive_previous = true; body.previous_run_id = instance.value.run_id
      if (preview.value?.requires_new_run) body.confirm_new_run = true
      if (legacyBaseline.value) body.replace_legacy = true
    }
    if (planSource.value === 'custom' && preview.value?.can_activate) body.plan = preview.value.plan
    body.allow_history_replay = allowReplay.value
    const result = await store.activate(body)
    if (result.status === 'done') { manageOpen.value = false; ElMessage.success('所选计划已启用') } else ElMessage.info('计划启用中，请稍候')
  } catch (e) { if (e !== 'cancel' && e !== 'close') fail(e) }
}
onMounted(() => { if(route.query.example || route.query.history_record) chainOpen.value=true; store.connect().catch(fail) })
onUnmounted(() => store.disconnect())
</script>

<style scoped>
.agent-entry{margin-bottom:14px}.agent-analyze{margin-top:9px}.agent-shortcuts{display:flex;gap:5px;margin:9px 0;flex-wrap:wrap}.agent-shortcuts :deep(.el-button+.el-button){margin-left:0}.agent-answer{padding:11px;background:#f5f8fc;border:1px solid #e1eaf4;border-radius:7px;font-size:12px;line-height:1.7;color:#526d8e}.agent-answer p{margin:0 0 8px}.agent-answer-text{white-space:pre-wrap;overflow-wrap:anywhere}.agent-answer-source{display:block;color:#6687b4;margin-bottom:8px}.agent-progress{font-size:11px;color:#6687b4;margin:10px 0}.agent-facts{display:flex;gap:10px;flex-wrap:wrap;font-size:10px;color:#8295ac}.agent-confirm{color:#af7b37;margin-top:9px!important}.agent-issues{padding-left:16px;margin:9px 0;color:#7b8ea6;font-size:11px}.agent-step{display:flex;justify-content:space-between;gap:10px;font-size:11px;margin:5px 0}.agent-evidence{border:0;margin-top:8px}.agent-evidence small{font-size:10px;color:#8b9caf}.manual-entry{margin-top:10px}.operations-heading>.el-tag{margin-left:auto}

.source-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 15px;background:#f0f5fc;border:1px solid #e1eaf7;border-radius:8px;margin-bottom:15px;font-size:11px;color:#8294af}.source-bar b{font-weight:500;color:#50739f}.source-bar>span{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.action-types button:disabled{opacity:.4;cursor:default}
.legacy-notice{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;background:#fff7e9;border:1px solid #f0dbb5;border-radius:8px;margin-bottom:15px;font-size:12px;color:#ac8041}.stage-card:disabled{opacity:.55;cursor:default}.source-row{display:flex;flex-direction:column;gap:4px;font-size:11px;color:#7287a4;margin:12px 0}.source-row span{word-break:break-all}.source-row small{color:#98a6ba}.resource-tile b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.operations-page{max-width:1680px;margin:auto;color:#293b55;padding:2px 3px 28px}.page-header{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:20px}h2{font-size:15px;margin:0;font-weight:600}h3{font-size:17px;font-weight:600}.plan-caption{display:flex;align-items:center;gap:8px;color:#8290a4;font-size:12px}.plan-caption>span:last-child{margin-left:10px}.live-dot{width:6px;height:6px;background:#2eaa8f;border-radius:50%}.live-dot.offline{background:#df9d45}.header-actions{display:flex;align-items:center;gap:8px}.header-actions :deep(.el-button+.el-button){margin-left:0}.clock{text-align:right;margin-right:12px}.clock b{font-family:Consolas,monospace;font-size:23px;font-weight:500;color:#3b5273}.clock small{display:block;font-size:10px;color:#8b99ab;margin-top:2px}.surface{background:#fff;border:1px solid #e3e9f1;border-radius:12px}.notice{margin:12px 0}.muted{color:#8a98ac;font-size:11px;line-height:1.6}.warning{color:#ce8739!important}.full{width:100%}.text-button{border:0;background:none;color:#557fbd;cursor:pointer;font:inherit;font-size:12px;padding:5px 0}.text-button:hover{color:#265fb2}.stage-flow{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:18px}.stage-card{padding:17px 18px 14px;background:#fff;border:1px solid #e3e9f1;border-radius:11px;cursor:pointer;color:#415572;text-align:left;transition:border-color .15s,box-shadow .15s}.stage-card:hover,.stage-card.active{border-color:var(--stage-color);box-shadow:0 0 0 2px color-mix(in srgb,var(--stage-color) 9%,transparent)}.stage-title{display:flex;gap:10px;align-items:center;font-size:14px}.stage-icon{display:flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:8px;background:color-mix(in srgb,var(--stage-color) 9%,white);color:var(--stage-color)}.stage-icon svg{width:17px}.stage-arrow{margin-left:auto;color:#b8c5d5;font-size:17px}.stage-card:last-child .stage-arrow{visibility:hidden}.stage-value{font-size:27px;font-weight:600;margin:14px 0 12px;color:#344e72}.stage-value small{font-size:11px;font-weight:400;color:#8797ad;margin-left:8px}.stage-bottom{display:flex;justify-content:space-between;gap:8px;font-size:10px;color:#8e9bb0}.stage-bottom>span:last-child{color:var(--stage-color)}.workbench{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:18px;align-items:start}.plan-area{min-width:0}.plan-panel,.resource-panel{padding:20px;margin-bottom:18px}.panel-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:16px}.heading-inline{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.grain-switch{display:flex;gap:3px;padding:4px;background:#f0f3f8;border-radius:8px}.grain-switch button{border:0;background:transparent;color:#8592a8;font-size:11px;padding:7px 11px;border-radius:5px;cursor:pointer;white-space:nowrap}.grain-switch button.active{background:#fff;color:#386fbd;box-shadow:0 1px 4px #253b6012;font-weight:600}.plan-strip{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:10px;color:#8595ab;padding:0 0 16px}.plan-strip em{font-style:normal;margin-left:9px;padding:3px 6px;background:#f4f6fa;border-radius:4px}.plan-strip b{font-weight:500;color:#4e6b92}.plan-strip i{font-style:normal;margin:0 9px;color:#c4cedd}.timeline-wrap{margin:5px 0 18px}.legend{display:flex;justify-content:flex-end;gap:15px;font-size:10px;color:#8a99ac;margin:5px 4px 0}.legend span{display:flex;align-items:center;gap:5px}.legend i{width:10px;height:7px;background:#4e80e8;border-radius:2px}.legend .forecast{opacity:.4}.legend .now{background:#ef6868;width:2px;height:10px}.blocked-reason{font-size:10px;line-height:1.8;color:#b48c58;max-width:190px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.plan-footnote{font-size:11px;color:#98a4b5;padding-top:14px}.clickable-table{cursor:pointer}.resource-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.resource-tile{padding:13px 12px;display:flex;align-items:center;justify-content:space-between;gap:8px;text-align:left;cursor:pointer;background:#f9fbfe;border:1px solid #e8edf4;border-radius:8px;color:#536b8c;font-size:11px}.resource-tile:hover,.resource-tile.picked{border-color:#8db0e8;background:#f3f7ff}.resource-tile.restricted{background:#fffaf2;border-color:#edcfaa}.resource-tile>span:first-child{min-width:0;flex:1}.resource-tile b{font-size:12px;font-weight:500;display:block}.resource-tile b small{display:inline;margin-left:6px}.resource-tile small{display:block;color:#92a1b6;font-size:10px;margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.resource-tile>span:last-child{flex-shrink:0;font-size:10px}.resource-ok{color:#6490bc}.operations-panel{padding:21px 20px;position:sticky;top:0;border-top:3px solid #4c80d6;scroll-margin-top:10px}.operations-heading{display:flex;align-items:center;gap:11px;border-bottom:1px solid #edf1f7;padding-bottom:17px;margin-bottom:17px}.operations-heading small{display:block;color:#91a0b4;font-size:10px;margin-top:6px}.operations-symbol{width:34px;height:34px;background:#eef4ff;display:flex;align-items:center;justify-content:center;border-radius:9px;color:#5988d1}.operations-symbol svg{width:18px}.form-step{font-size:12px;font-weight:600;color:#5b7190;display:flex;align-items:center;gap:8px;margin:16px 0 11px}.form-step>span{width:18px;height:18px;border-radius:50%;background:#edf3fc;color:#7296cc;font-size:10px;text-align:center;line-height:18px;font-weight:400}.action-types{display:grid;grid-template-columns:repeat(2,1fr);gap:7px;margin:12px 0 17px}.action-types button{border:1px solid #e2e9f2;background:#fff;border-radius:6px;padding:8px 4px;font-size:11px;color:#8190a6;cursor:pointer}.action-types button.selected{color:#4479c4;background:#f1f6ff;border-color:#8fb1e6}.operations-form :deep(.el-form-item){margin-bottom:13px}.operations-form :deep(.el-form-item__label){font-size:11px;color:#7f90a8;padding-bottom:5px}.original-value{font-size:11px;color:#91a0b4;margin-bottom:12px;padding:9px 10px;background:#f6f8fc;border-radius:5px}.input-unit{display:flex;align-items:center;gap:9px;font-size:11px;color:#8393a9}.field-hint{font-size:10px;color:#9ba7b9;margin:-6px 0 12px}.date-input{box-sizing:border-box;width:100%;height:33px;border:1px solid #dce3ed;border-radius:5px;padding:4px 9px;color:#566d8e;font:inherit;font-size:12px}.optional-fields{border:0;margin:14px 0 10px}.optional-fields :deep(.el-collapse-item__header){font-size:10px;color:#9ba7b9;height:32px;border:0}.optional-fields :deep(.el-collapse-item__wrap){border:0}.submit-change{width:100%;margin:5px 0}.plan-action{border-top:1px solid #edf1f7;margin-top:17px;padding-top:2px}.assistant-box{border:0;margin-top:15px}.assistant-box :deep(.el-collapse-item__header){font-size:11px;color:#8b9bb0}.assistant-box :deep(.el-collapse-item__wrap){border:0}.assistant-box .el-button{margin-top:10px}.action-prompt{display:flex;flex-direction:column;gap:7px;padding:12px;background:#eef7f5;border:1px solid #d8ebe5;border-radius:8px;margin-bottom:17px;color:#428c7c;font-size:12px}.action-prompt>span{font-size:10px;color:#83a99e}.action-prompt .el-button{margin-top:3px}.recovery-confirm{padding:14px;background:#eef8f4;color:#4c9483;border-radius:6px;font-size:12px;margin-bottom:12px}.start-plan{text-align:center;padding:60px 20px 70px}.start-icon{width:50px;height:50px;margin:0 auto 20px;padding:12px;box-sizing:border-box;background:#edf3ff;color:#7397d1;border-radius:14px}.start-plan p{font-size:12px;color:#98a4b6;margin:12px 0 25px}.start-plan>.text-button{display:block;margin:14px auto}.operations-placeholder{text-align:center;padding:40px 10px;color:#9ba9bb}.operations-placeholder>svg{width:30px;opacity:.5}.operations-placeholder h3{font-size:13px}.operations-placeholder p{font-size:11px;line-height:1.9}.candidate-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:18px 0}.candidate{padding:16px;border:1px solid #e0e8f4;border-radius:9px;background:#fff;text-align:left;cursor:pointer;color:#6d83a3}.candidate.selected{border-color:#6d99de;background:#f5f9ff;box-shadow:0 0 0 2px #6d99de12}.candidate>span{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12px}.candidate strong{display:block;font-size:28px;color:#3c5f90;font-weight:600;margin:18px 0 10px}.candidate strong small{font-size:10px;color:#8a9db7;font-weight:400;margin-left:7px}.candidate p{font-size:11px;color:#9aa8bb;margin:0}.adjust-summary{display:flex;gap:24px;flex-wrap:wrap;padding:15px;background:#f6f8fc;border-radius:7px;color:#8a9ab0;font-size:11px;margin-bottom:18px}.adjust-summary b{color:#55779f;font-weight:500;margin-left:6px}.details-collapse{margin-top:18px}.details-collapse p{font-size:11px;color:#91a0b5;line-height:1.8}.current-plan{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:18px;font-size:12px}.current-plan span{font-size:11px;color:#92a1b6}.plan-form{margin-top:20px}.preview-box{padding:14px;background:#f4f8fc;border:1px solid #e2ebf5;border-radius:7px;font-size:12px;line-height:1.8;margin-top:15px}.preview-box small{color:#8d9fb7;margin-left:15px}:deep(.el-table){--el-table-header-bg-color:#f7f9fc;--el-table-border-color:#edf1f6;color:#607590}:deep(.el-table th.el-table__cell){color:#8b9bb0;font-weight:500;font-size:11px}:deep(.el-table td.el-table__cell){padding:11px 0;font-size:11px}:deep(.el-table b){font-weight:500}:deep(.el-drawer__title){font-size:17px;color:#3d5678}:deep(.el-collapse-item__header){font-size:11px;color:#8294ae}:deep(.el-input-number){max-width:100%}:deep(.el-drawer__footer){border-top:1px solid #edf1f7;padding-top:16px}
.task-heading{margin:17px 0 12px}.summary-collapse{margin-top:16px}.candidate-caption{display:block;margin-top:16px;font-size:11px;color:#899bb3}.candidate strong{margin:8px 0 12px}.candidate strong.completion-time{font-size:19px}.delivery-assessment{margin-bottom:15px}.menu-arrow{margin-left:7px}.stage-card{padding:13px 16px}.stage-title{margin-bottom:12px}.stage-title .el-tag{margin-left:auto}.stage-bottom{font-size:12px}.stage-flow{gap:12px}.stage-bottom>span:last-child{font-size:11px}.resource-heading{margin-bottom:0}.resource-heading h2 small{font-size:12px;color:#8a98ac;font-weight:400;margin-left:5px}.resource-list{margin-top:15px}.fault-shortcuts{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.fault-shortcuts button{background:#fff8eb;border:1px solid #edcfaa;border-radius:6px;color:#b67b35;padding:8px 10px;cursor:pointer}.action-select{margin-top:14px}.operations-heading{padding-bottom:13px;margin-bottom:6px}.action-prompt{flex-direction:row;align-items:center;justify-content:space-between;padding:8px 10px;margin:12px 0}.action-prompt>span{font-size:12px;color:#428c7c}.action-prompt .el-button{margin:0}.operations-form :deep(.el-form-item__label){font-size:12px}.muted,.blocked-reason{font-size:12px}.plan-strip{font-size:12px;line-height:1.7}.header-actions{flex-shrink:0}.operations-placeholder{padding:24px 8px}.start-plan h3{margin-bottom:25px}.text-button:disabled{opacity:.5;cursor:default}
@media(min-width:1600px){.workbench{grid-template-columns:minmax(0,1fr) 360px}.operations-panel{padding:22px 24px}}
@media(max-width:1180px){.workbench{grid-template-columns:minmax(0,1fr) 300px;gap:12px}.plan-panel,.resource-panel{padding:16px}.panel-heading{align-items:flex-start;flex-wrap:wrap}.stage-card{padding:14px 12px}.stage-flow{gap:10px}.resource-list{grid-template-columns:1fr}.clock b{font-size:20px}.plan-caption>span:last-child{max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
@media(max-width:900px){.workbench{grid-template-columns:minmax(0,1fr)}.operations-panel{position:static;grid-row:1}.operations-form{display:block}.operations-form>.form-step,.operations-form>.action-types,.operations-form>.original-value,.operations-form>.submit-change,.operations-form>.optional-fields,.operations-form>.recovery-confirm,.operations-form>.field-hint{grid-column:1/-1}.operations-form>.action-types{grid-template-columns:repeat(4,1fr)}.operations-heading{margin-bottom:4px}.operations-placeholder{padding:15px}.stage-flow{grid-template-columns:repeat(2,minmax(0,1fr))}.page-header{align-items:flex-start}.header-actions{gap:4px}.header-actions .el-button{padding:8px}.plan-caption>span:last-child{display:none}.plan-strip{line-height:1.8}}
@media(max-width:560px){.page-header{flex-wrap:wrap}.header-actions{width:100%}.clock{margin-right:auto;text-align:left}.stage-title{gap:7px;flex-wrap:wrap}.stage-title .el-tag{margin-left:0}.stage-bottom{font-size:11px}.header-actions .el-button{font-size:10px}.stage-value{font-size:23px}.stage-bottom{flex-direction:column;gap:5px}.candidate-grid{grid-template-columns:1fr}.operations-form{display:block}.operations-form>.action-types{grid-template-columns:repeat(2,1fr)}.plan-panel{padding:13px}.grain-switch button{padding:6px 10px}}
</style>
