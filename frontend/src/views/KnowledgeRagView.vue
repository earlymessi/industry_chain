<template>

  <div class="page">

    <el-tabs v-model="activeTab" class="kb-tabs" @tab-change="onTabChange">

      <el-tab-pane label="知识库问答" name="chat">

        <div class="streamlit-wrap">

          <el-alert

            v-if="streamlitHint"

            class="streamlit-hint"

            type="info"

            :closable="false"

            show-icon

            :title="streamlitHint"

          />

          <iframe

            v-if="streamlitUrl"

            class="streamlit-frame"

            :src="streamlitUrl"

            title="家电产业链知识库问答（Streamlit）"

            @load="onStreamlitLoad"

          />

        </div>

      </el-tab-pane>



      <el-tab-pane label="文档管理" name="docs" lazy>

        <KnowledgeDocManage ref="docManageRef" />

      </el-tab-pane>

    </el-tabs>

  </div>

</template>



<script setup>

import { nextTick, onMounted, ref } from 'vue'

import { api } from '../api/client'

import KnowledgeDocManage from '../components/KnowledgeDocManage.vue'



const activeTab = ref('chat')

const docManageRef = ref(null)

const streamlitUrl = ref('')

const streamlitHint = ref('正在连接 Streamlit 知识库…')



const defaultStreamlitUrl =

  import.meta.env.VITE_RAG_STREAMLIT_URL || 'http://127.0.0.1:8501'



async function resolveStreamlitUrl() {

  try {

    const { data } = await api.get('/api/rag/streamlit-url', { timeout: 8000 })

    if (data?.url) {

      streamlitUrl.value = data.url

      return

    }

  } catch {

    // 回退到构建时配置或默认 8501

  }

  streamlitUrl.value = defaultStreamlitUrl

}



function onStreamlitLoad() {

  streamlitHint.value = ''

}



function onTabChange(name) {

  nextTick(() => {

    if (name === 'docs') docManageRef.value?.refresh()

  })

}



onMounted(() => {

  resolveStreamlitUrl()

})

</script>



<style scoped>

.page {

  height: calc(100vh - 55px - 40px);

  display: flex;

  flex-direction: column;

  background: #f0f2f5;

}



.kb-tabs {

  flex: 1;

  min-height: 0;

  display: flex;

  flex-direction: column;

}



:deep(.kb-tabs .el-tabs__header) {

  margin: 0 0 8px;

  background: #fff;

  padding: 0 12px;

  border-radius: 8px;

  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);

}



:deep(.kb-tabs .el-tabs__content) {

  flex: 1;

  min-height: 0;

}



:deep(.kb-tabs .el-tab-pane) {

  height: 100%;

  display: flex;

  flex-direction: column;

  min-height: 0;

}



.streamlit-wrap {

  flex: 1;

  min-height: 0;

  display: flex;

  flex-direction: column;

  background: #f0f2f5;

  border-radius: 8px;

  overflow: hidden;

}



.streamlit-hint {

  flex-shrink: 0;

  margin: 0 0 8px;

}



.streamlit-frame {

  flex: 1;

  width: 100%;

  min-height: 0;

  border: none;

  display: block;

  background: #f0f2f5;

}

</style>

