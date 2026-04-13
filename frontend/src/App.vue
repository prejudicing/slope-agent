<template>
  <div class="app-container">
    <div class="page-header">
      <h1>高切坡系统智能查询 Agent</h1>
      <p>查询高切坡基本信息、群测群防、专业监测、预警专报与巡查记录</p>
    </div>

    <el-card shadow="never" class="top-card">
      <QueryInput
        v-model:question="question"
        :loading="loading"
        @submit="handleSubmit"
      />
    </el-card>

    <div class="grid-container">
      <SqlPreview :sql="sql" />
      <SummaryPanel :summary="summary" />
    </div>

    <div class="grid-container single">
      <ResultPanel :columns="columns" :rows="rows" />
    </div>

    <div class="grid-container single">
      <AgentLogPanel :logs="logs" />
    </div>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      class="error-alert"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import QueryInput from './components/QueryInput.vue'
import SqlPreview from './components/SqlPreview.vue'
import ResultPanel from './components/ResultPanel.vue'
import SummaryPanel from './components/SummaryPanel.vue'
import AgentLogPanel from './components/AgentLogPanel.vue'
import { postQuery } from './api/query'

const question = ref('')
const sql = ref('')
const summary = ref('')
const columns = ref<string[]>([])
const rows = ref<Record<string, string>[]>([])
const logs = ref('')
const error = ref('')
const loading = ref(false)

const handleSubmit = async () => {
  if (!question.value.trim()) {
    error.value = '请输入问题'
    return
  }

  loading.value = true
  sql.value = ''
  summary.value = ''
  columns.value = []
  rows.value = []
  logs.value = ''
  error.value = ''

  try {
    const res = await postQuery(question.value)

    sql.value = res.sql || ''
    summary.value = res.summary || res.result || ''
    columns.value = res.columns || []
    rows.value = res.rows || []
    logs.value = res.logs || ''
    error.value = res.error || ''
  } catch (err: any) {
    error.value = err?.message || '请求失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.app-container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 32px 28px 48px;
}

.page-header {
  margin-bottom: 22px;
  padding-left: 2px;
}

.page-header h1 {
  margin: 0 0 8px;
  color: #1f2d3d;
  font-size: 30px;
  letter-spacing: 0;
}

.page-header p {
  margin: 0;
  color: #5f6f86;
  font-size: 15px;
}

.top-card {
  margin-bottom: 22px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
}

.grid-container {
  display: grid;
  grid-template-columns: 1fr;
  gap: 18px;
  margin-bottom: 18px;
  min-width: 0;
}

.grid-container.single {
  grid-template-columns: 1fr;
}

.grid-container > * {
  min-width: 0;
}

.error-alert {
  margin-top: 20px;
  border-radius: 8px;
}

@media (min-width: 992px) {
  .grid-container {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 640px) {
  .app-container {
    width: 100%;
    padding: 18px 12px 32px;
    overflow-x: hidden;
  }

  .page-header h1 {
    font-size: 24px;
  }

  .page-header p {
    font-size: 14px;
    line-height: 1.6;
  }
}
</style>
