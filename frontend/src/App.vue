<template>
  <div class="app-container">
    <div class="page-header">
      <h1>高切坡智能查询</h1>
      <p>输入业务问题，系统将返回查询结果和结果解读。</p>
    </div>

    <el-card shadow="never" class="top-card">
      <QueryInput
        v-model:question="question"
        :loading="loading"
        @submit="handleSubmit"
      />
    </el-card>

    <el-card v-if="loading" shadow="never" class="status-card">
      <div class="status-panel">
        <el-icon class="status-icon is-loading"><Loading /></el-icon>
        <div class="status-copy">
          <h3>正在查询</h3>
          <p>系统正在分析问题并查询数据库，请稍候。</p>
        </div>
      </div>
    </el-card>

    <div class="grid-container single">
      <SummaryPanel :summary="summary" />
    </div>

    <div class="grid-container single">
      <ResultPanel :columns="columns" :rows="rows" />
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
import { Loading } from '@element-plus/icons-vue'
import QueryInput from './components/QueryInput.vue'
import ResultPanel from './components/ResultPanel.vue'
import SummaryPanel from './components/SummaryPanel.vue'
import { streamQuery } from './api/query'

const question = ref('')
const summary = ref('')
const columns = ref<string[]>([])
const rows = ref<Record<string, string>[]>([])
const error = ref('')
const loading = ref(false)

const handleSubmit = async () => {
  if (!question.value.trim()) {
    error.value = '请输入问题'
    return
  }

  loading.value = true
  summary.value = ''
  columns.value = []
  rows.value = []
  error.value = ''

  try {
    await streamQuery(question.value, (event) => {
      if (event.type === 'summary') {
        summary.value = event.summary || ''
        return
      }

      if (event.type === 'final') {
        const res = event.data
        summary.value = res.summary || res.result || summary.value
        columns.value = res.columns || []
        rows.value = res.rows || []
        error.value = res.error || ''
        return
      }

      if (event.type === 'error') {
        error.value = event.message
      }
    })
  } catch (err: any) {
    error.value = err?.message || '请求失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.app-container {
  max-width: 1360px;
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

.top-card,
.status-card {
  margin-bottom: 22px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
}

.status-panel {
  display: flex;
  align-items: center;
  gap: 14px;
}

.status-icon {
  color: #409eff;
  font-size: 22px;
}

.status-copy h3 {
  margin: 0 0 4px;
  color: #1f2d3d;
  font-size: 16px;
}

.status-copy p {
  margin: 0;
  color: #5f6f86;
  font-size: 14px;
}

.grid-container {
  display: grid;
  grid-template-columns: 1fr;
  gap: 18px;
  margin-bottom: 18px;
  min-width: 0;
}

.grid-container > * {
  min-width: 0;
}

.error-alert {
  margin-top: 20px;
  border-radius: 8px;
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

  .status-panel {
    align-items: flex-start;
  }
}
</style>
