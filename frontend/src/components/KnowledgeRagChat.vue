<template>
  <div class="rag-chat">
    <section class="hero">
      <h1 class="hero-title">家电产业链供应链知识问答</h1>
      <p class="hero-sub">
        基于知识库检索，解答冰箱、洗衣机、空调、热水器等品类的上游零部件、供应商关系、物流协同与数字化制造问题。
      </p>
      <div class="hero-tags">
        <span>上游零部件</span>
        <span>供应商与合作</span>
        <span>物流与数字化</span>
      </div>
    </section>

    <div class="toolbar">
      <div class="toolbar-left">
        <el-button size="small" @click="clearChat">清空会话</el-button>
        <el-button size="small" :loading="rebuilding" :disabled="rebuilding" @click="rebuildKb">
          {{ rebuilding ? '重建中…' : '重建知识库' }}
        </el-button>
        <span v-if="rebuilding" class="rebuild-hint">约需 3～5 分钟，请勿关闭页面</span>
      </div>
      <div class="toolbar-right">
        <span class="meta">向量片段 {{ docCount }}</span>
        <el-tag v-if="statusChecking" type="info" size="small">检测中</el-tag>
        <el-tag v-else-if="workerReady" type="success" size="small">模型已预热</el-tag>
        <el-tag v-else :type="ragOnline ? 'success' : 'warning'" size="small">
          {{ ragOnline ? 'RAG 在线' : 'RAG 离线' }}
        </el-tag>
      </div>
    </div>

    <div class="shortcuts">
      <el-button
        v-for="q in shortcuts"
        :key="q"
        size="small"
        round
        :disabled="loading"
        @click="askShortcut(q)"
      >
        {{ q }}
      </el-button>
    </div>

    <div ref="scrollRef" class="messages">
      <el-alert
        v-if="!messages.length"
        type="info"
        :closable="false"
        show-icon
        class="empty-tip"
        title="可先点击上方示例问题，也可直接询问零部件供应、供应商评估、缺货替代、物流协同等家电产业链与供应链相关问题。"
      />

      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <div class="avatar">{{ m.role === 'user' ? '🧑' : '🏭' }}</div>
        <div class="bubble">
          <div v-if="m.role === 'assistant'" class="answer" v-html="renderMarkdown(m.content)" />
          <div v-else class="text">{{ m.content }}</div>

          <div v-if="m.references?.length" class="refs">
            <div class="refs-title">参考来源</div>
            <el-collapse accordion @change="onRefExpand">
              <el-collapse-item
                v-for="(ref, ri) in m.references"
                :key="`${i}-${ri}`"
                :title="ref"
                :name="ref"
              >
                <div v-loading="previewLoading === ref" class="ref-preview">
                  {{ refPreviews[ref] || '点击展开加载片段预览…' }}
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
        </div>
      </div>

      <div v-if="loading" class="msg assistant">
        <div class="avatar">🏭</div>
        <div class="bubble loading-bubble">
          <el-icon class="is-loading"><Loading /></el-icon>
          正在检索知识库并生成回答（首次提问需加载 Agent，约 30～90 秒）…
        </div>
      </div>
    </div>

    <div class="composer">
      <el-input
        v-model="inputText"
        type="textarea"
        :rows="2"
        resize="none"
        placeholder="请输入问题，例如：洗衣机供应链的核心风险有哪些？"
        :disabled="loading"
        @keydown.enter.exact.prevent="send"
      />
      <el-button type="primary" :loading="loading" :disabled="!inputText.trim()" @click="send">
        发送
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { api } from '../api/client'
import { renderMarkdown } from '../utils/markdown'

const shortcuts = [
  '冰箱/冷柜的供应链主要包括哪些环节？',
  '洗衣机供应链的核心风险有哪些？',
  '大件家电物流配送的供应商有哪些？',
  '冰箱/冷柜压缩机的供应商有哪些？',
  '洗衣机BLDC/DD电机的供应商有哪些？',
]

const messages = ref([])
const inputText = ref('')
const loading = ref(false)
const rebuilding = ref(false)
const ragOnline = ref(false)
const statusChecking = ref(true)
const workerReady = ref(false)
const docCount = ref(0)
const scrollRef = ref(null)
const refPreviews = ref({})
const previewLoading = ref('')

async function scrollBottom() {
  await nextTick()
  const el = scrollRef.value
  if (el) el.scrollTop = el.scrollHeight
}

async function checkStatus() {
  statusChecking.value = true
  try {
    const { data } = await api.get('/api/rag/status', { timeout: 10000 })
    ragOnline.value = !!data?.available
    if (typeof data?.doc_count === 'number') docCount.value = data.doc_count
    workerReady.value = !!data?.worker_ready
  } catch {
    ragOnline.value = false
  } finally {
    statusChecking.value = false
  }
}

async function warmupRag() {
  try {
    const { data } = await api.post('/api/rag/warmup', {}, { timeout: 180000 })
    workerReady.value = !!data?.worker_ready
    if (typeof data?.doc_count === 'number' && data.doc_count > 0) {
      docCount.value = data.doc_count
    }
    if (data?.ok) ragOnline.value = true
  } catch {
    // 预热失败不阻断页面，首次提问时会再次尝试
  }
}

function buildApiMessages() {
  return messages.value
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .map((m) => ({ role: m.role, content: m.content }))
}

async function send() {
  const text = inputText.value?.trim()
  if (!text || loading.value) return

  if (!workerReady.value) {
    await warmupRag()
  }

  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  loading.value = true
  await scrollBottom()

  try {
    const { data } = await api.post(
      '/api/rag/chat',
      { messages: buildApiMessages() },
      { timeout: 300000 },
    )
    messages.value.push({
      role: 'assistant',
      content: data?.answer || '暂无回答',
      references: Array.isArray(data?.references) ? data.references : [],
    })
    await checkStatus()
  } catch (err) {
    const detail = err?.response?.data?.detail || err?.message || '问答失败'
    ElMessage.error(detail)
    messages.value.push({
      role: 'assistant',
      content: `服务暂时不可用：${detail}`,
      references: [],
    })
  } finally {
    loading.value = false
    await scrollBottom()
  }
}

function askShortcut(q) {
  inputText.value = q
  send()
}

function clearChat() {
  messages.value = []
  refPreviews.value = {}
}

async function rebuildKb() {
  if (rebuilding.value) return
  try {
    await ElMessageBox.confirm(
      '将清空向量索引并按 data 目录全量重建。当前约 2500 条片段，通常需要 3～5 分钟，期间按钮会显示加载中。是否继续？',
      '重建知识库',
      { type: 'warning', confirmButtonText: '重建', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  rebuilding.value = true
  let loadingMsg = null
  try {
    loadingMsg = ElMessage({
      message: '正在重建知识库，约需 3～5 分钟，请耐心等待…',
      type: 'info',
      duration: 0,
      showClose: true,
    })
    const { data } = await api.post('/api/rag/kb', { action: 'rebuild' }, { timeout: 600000 })
    ElMessage.success(data?.message || '知识库重建完成')
  } catch (err) {
    const msg = err?.response?.data?.detail || err?.message || '重建失败'
    if (String(msg).includes('timeout')) {
      ElMessage.error('重建超时：后台可能仍在继续，请稍等 1 分钟后刷新页面查看向量片段数')
    } else {
      ElMessage.error(msg)
    }
  } finally {
    rebuilding.value = false
    loadingMsg?.close()
    checkStatus()
  }
}

async function onRefExpand(reference) {
  if (reference) await loadRefPreview(reference)
}

async function loadRefPreview(reference) {
  if (!reference || refPreviews.value[reference]) return
  previewLoading.value = reference
  try {
    const { data } = await api.post('/api/rag/reference-preview', { reference }, { timeout: 120000 })
    refPreviews.value = { ...refPreviews.value, [reference]: data?.preview || '暂无预览' }
  } catch (err) {
    refPreviews.value = {
      ...refPreviews.value,
      [reference]: err?.response?.data?.detail || err?.message || '加载预览失败',
    }
  } finally {
    previewLoading.value = ''
  }
}

onMounted(() => {
  checkStatus()
  warmupRag()
})

defineExpose({ refreshStatus: checkStatus, warmupRag })
</script>

<style scoped>
.rag-chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  gap: 10px;
}

.hero {
  flex-shrink: 0;
  border: 1px solid #d9e3ea;
  border-radius: 16px;
  padding: 14px 16px;
  background: linear-gradient(150deg, rgba(255, 255, 255, 0.94), rgba(236, 243, 247, 0.92));
  box-shadow: 0 8px 24px rgba(25, 50, 74, 0.06);
}

.hero-title {
  margin: 0;
  font-size: 1.35rem;
  font-weight: 800;
  color: #19324a;
}

.hero-sub {
  margin: 8px 0 10px;
  font-size: 13px;
  line-height: 1.6;
  color: #2f4d63;
}

.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.hero-tags span {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(61, 169, 163, 0.12);
  color: #1f5f5b;
  border: 1px solid rgba(61, 169, 163, 0.25);
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.meta {
  font-size: 13px;
  color: #606266;
}

.rebuild-hint {
  font-size: 12px;
  color: #e6a23c;
}

.shortcuts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
  background: #f5f8fa;
  border: 1px solid #e4e7ed;
  border-radius: 12px;
}

.empty-tip {
  margin-bottom: 8px;
}

.msg {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
  align-items: flex-start;
}

.msg.user {
  flex-direction: row-reverse;
}

.avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
}

.bubble {
  max-width: min(760px, 88%);
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.65;
}

.msg.user .bubble {
  background: #3da9a3;
  color: #fff;
}

.msg.assistant .bubble {
  background: #fff;
  border: 1px solid #e4e7ed;
  color: #303133;
}

.loading-bubble {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #606266;
}

.text {
  white-space: pre-wrap;
  word-break: break-word;
}

.answer :deep(p) {
  margin: 0 0 8px;
}

.answer :deep(p:last-child) {
  margin-bottom: 0;
}

.answer :deep(ul) {
  margin: 0 0 8px 18px;
  padding: 0;
}

.refs {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed #dcdfe6;
}

.refs-title {
  font-size: 12px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 6px;
}

.ref-preview {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
  min-height: 24px;
}

.composer {
  flex-shrink: 0;
  display: flex;
  gap: 8px;
  align-items: flex-end;
  padding-top: 2px;
}

.composer .el-textarea {
  flex: 1;
}
</style>
