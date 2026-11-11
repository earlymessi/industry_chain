<template>
  <div class="doc-manage">
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-upload
            :show-file-list="false"
            :auto-upload="false"
            :disabled="uploading"
            accept=".txt,.pdf,.docx,.json"
            @change="onFilePick"
          >
            <el-button type="primary" :loading="uploading">
              <el-icon><Upload /></el-icon>
              上传文档
            </el-button>
          </el-upload>
          <el-button :loading="syncing" @click="syncAll">同步入库</el-button>
          <el-button :loading="loading" @click="loadDocuments">刷新</el-button>
        </div>
        <div class="toolbar-right">
          <span class="meta">向量片段 {{ docCount }}</span>
          <el-tag :type="ragOnline ? 'success' : 'warning'" size="small">
            {{ ragOnline ? 'RAG 在线' : 'RAG 离线' }}
          </el-tag>
        </div>
      </div>
      <div class="tip">管理家电产业链知识库文档；支持 txt / pdf / docx / json 上传（≤20MB）。更新文件后请点击「同步入库」或到问答页「重建知识库」。</div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table ref="tableRef" v-loading="loading" :data="documents" stripe border empty-text="暂无知识库文档">
        <el-table-column prop="name" label="文件名" min-width="180" show-overflow-tooltip />
        <el-table-column prop="path" label="路径" min-width="160" show-overflow-tooltip />
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ formatSize(row.size) }}</template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="向量片段" width="96" align="center" />
        <el-table-column label="入库状态" width="108" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.indexed" type="success" size="small">已入库</el-tag>
            <el-tag v-else type="info" size="small">未入库</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="文件" width="88" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.on_disk" type="info" size="small">本地</el-tag>
            <el-tag v-else type="warning" size="small">仅向量</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="168" show-overflow-tooltip />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :loading="previewingPath === row.path" @click="previewOne(row)">
              查看
            </el-button>
            <el-button
              link
              type="primary"
              :disabled="!row.on_disk"
              :loading="ingestingPath === row.path"
              @click="ingestOne(row)"
            >
              重新入库
            </el-button>
            <el-button
              link
              type="danger"
              :loading="deletingPath === row.path"
              @click="removeOne(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="previewVisible" :title="previewTitle" width="720px" destroy-on-close>
      <pre class="preview-body">{{ previewText }}</pre>
    </el-dialog>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import { api } from '../api/client'

const documents = ref([])
const docCount = ref(0)
const loading = ref(false)
const uploading = ref(false)
const syncing = ref(false)
const ragOnline = ref(false)
const ingestingPath = ref('')
const deletingPath = ref('')
const previewingPath = ref('')
const previewVisible = ref(false)
const previewTitle = ref('')
const previewText = ref('')
const tableRef = ref(null)

function formatSize(bytes) {
  const n = Number(bytes) || 0
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

async function checkStatus() {
  try {
    const { data } = await api.get('/api/rag/status')
    ragOnline.value = !!data?.available
    if (typeof data?.doc_count === 'number') docCount.value = data.doc_count
  } catch {
    ragOnline.value = false
  }
}

async function loadDocuments() {
  loading.value = true
  try {
    const { data } = await api.get('/api/rag/documents', { timeout: 180000 })
    documents.value = data?.documents || []
    if (typeof data?.doc_count === 'number') docCount.value = data.doc_count
    await nextTick()
    tableRef.value?.doLayout?.()
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '加载文档列表失败')
  } finally {
    loading.value = false
  }
}

async function refresh() {
  await Promise.all([checkStatus(), loadDocuments()])
}

defineExpose({ refresh })

async function onFilePick(uploadFile) {
  const raw = uploadFile?.raw
  if (!raw) return
  uploading.value = true
  try {
    const form = new FormData()
    form.append('file', raw, raw.name)
    const { data } = await api.post('/api/rag/documents', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    })
    ElMessage.success(data?.message || '上传成功')
    await loadDocuments()
    await checkStatus()
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function syncAll() {
  syncing.value = true
  try {
    const { data } = await api.post('/api/rag/kb', { action: 'ingest' })
    ElMessage.success(data?.message || '同步完成')
    await loadDocuments()
    await checkStatus()
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '同步失败')
  } finally {
    syncing.value = false
  }
}

async function ingestOne(row) {
  if (!row.on_disk) {
    ElMessage.warning('该文档无本地文件，无法重新入库')
    return
  }
  ingestingPath.value = row.path
  try {
    const { data } = await api.post('/api/rag/documents/ingest', { path: row.path })
    ElMessage.success(data?.message || '入库完成')
    await loadDocuments()
    await checkStatus()
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '入库失败')
  } finally {
    ingestingPath.value = ''
  }
}

async function removeOne(row) {
  try {
    await ElMessageBox.confirm(`确定删除「${row.name}」？删除后问答将不再引用该文档。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  deletingPath.value = row.path
  try {
    const { data } = await api.delete('/api/rag/documents', { data: { path: row.path } })
    ElMessage.success(data?.message || '删除成功')
    await loadDocuments()
    await checkStatus()
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '删除失败')
  } finally {
    deletingPath.value = ''
  }
}

async function previewOne(row) {
  previewingPath.value = row.path
  try {
    const { data } = await api.get('/api/rag/documents/preview', {
      params: { path: row.path },
      timeout: 120000,
    })
    previewTitle.value = row.name
    previewText.value = data?.preview || '暂无内容'
    previewVisible.value = true
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '读取文档失败')
  } finally {
    previewingPath.value = ''
  }
}

onMounted(() => {
  refresh()
})
</script>

<style scoped>
.doc-manage {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  min-height: 0;
}

.toolbar-card,
.table-card {
  border-radius: 8px;
}

.table-card {
  flex: 1;
  min-height: 0;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.meta {
  font-size: 13px;
  color: #606266;
}

.tip {
  margin-top: 10px;
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
}

.preview-body {
  margin: 0;
  max-height: 60vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
  font-family: inherit;
}
</style>
