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

    <div class="grid-container single">
      <AgentLogPanel
        :logs="logs"
        :steps="thinkingSteps"
        :loading="loading"
        :expanded="thinkingExpanded"
        @toggle="thinkingExpanded = !thinkingExpanded"
      />
    </div>

    <div class="grid-container">
      <SqlPreview :sql="sql" />
      <SummaryPanel :summary="summary" />
    </div>

    <div class="grid-container single">
      <SpeechPlayer :summary="summary" :columns="columns" :rows="rows" />
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
import QueryInput from './components/QueryInput.vue'
import SqlPreview from './components/SqlPreview.vue'
import ResultPanel from './components/ResultPanel.vue'
import SummaryPanel from './components/SummaryPanel.vue'
import AgentLogPanel from './components/AgentLogPanel.vue'
import SpeechPlayer from './components/SpeechPlayer.vue'
import { streamQuery } from './api/query'
import type { ThinkingStep } from './types/query'

// 页面主状态：SQL、表格、总结和日志分别展示，避免把 Final Answer 当作表格数据。
const question = ref('')
const sql = ref('')
const summary = ref('')
const columns = ref<string[]>([])
const rows = ref<Record<string, string>[]>([])
const logs = ref('')
const thinkingSteps = ref<ThinkingStep[]>([])
const thinkingExpanded = ref(false)
const error = ref('')
const loading = ref(false)

// 把后端 SSE progress 事件追加到“思考过程”面板，同时维护完整文本日志。
const appendThinking = (
  title: string,
  detail?: string,
  status: ThinkingStep['status'] = 'running'
) => {
  const time = new Date().toLocaleTimeString()
  if (thinkingSteps.value.length) {
    thinkingSteps.value[thinkingSteps.value.length - 1].status = 'done'
  }
  thinkingSteps.value.push({
    id: thinkingSteps.value.length + 1,
    time,
    title,
    detail,
    status,
  })
  logs.value += `[${time}] ${title}\n`
  if (detail) {
    logs.value += `${detail}\n`
  }
  logs.value += '\n'
}

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
  thinkingSteps.value = []
  thinkingExpanded.value = true
  error.value = ''

  try {
    appendThinking('开始理解问题并准备查询')

    // 后端按 SSE 持续推送 progress/sql/summary/final，前端收到后分区更新页面。
    await streamQuery(question.value, (event) => {
      if (event.type === 'progress') {
        appendThinking(event.message, event.detail)
        return
      }

      if (event.type === 'sql') {
        sql.value = event.sql || ''
        appendThinking('已生成 SQL', event.sql)
        return
      }

      if (event.type === 'summary') {
        summary.value = event.summary || ''
        appendThinking(event.message || '已生成查询总结', event.summary)
        return
      }

      if (event.type === 'final') {
        const res = event.data
        // final 中的 columns/rows 来自最后一次成功 SQL 查询，是结果表格的数据源。
        sql.value = res.sql || sql.value
        summary.value = res.summary || res.result || summary.value
        columns.value = res.columns || []
        rows.value = res.rows || []
        logs.value += res.logs ? `完整 Agent 日志：\n${res.logs}\n` : ''
        error.value = res.error || ''
        if (thinkingSteps.value.length) {
          thinkingSteps.value[thinkingSteps.value.length - 1].status = 'done'
        }
        thinkingExpanded.value = false
        return
      }

      if (event.type === 'error') {
        error.value = event.message
        appendThinking('查询失败', event.message, 'error')
      }
    })
  } catch (err: any) {
    error.value = err?.message || '请求失败'
    appendThinking('请求失败', error.value, 'error')
  } finally {
    if (
      thinkingSteps.value.length &&
      thinkingSteps.value[thinkingSteps.value.length - 1].status === 'running'
    ) {
      thinkingSteps.value[thinkingSteps.value.length - 1].status = error.value ? 'error' : 'done'
    }
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
