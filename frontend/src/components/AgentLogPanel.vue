<template>
  <el-card shadow="never" class="panel-card thinking-card">
    <template #header>
      <div class="panel-header">
        <div>
          <span>思考过程</span>
          <span class="status-text">{{ statusText }}</span>
        </div>
        <el-button text type="primary" @click="emit('toggle')">
          {{ expanded ? '收起' : '展开' }}
        </el-button>
      </div>
    </template>

    <div v-if="!expanded" class="collapsed-view">
      <span class="pulse" :class="{ active: loading }"></span>
      {{ collapsedText }}
    </div>

    <div v-else class="thinking-body">
      <div v-if="steps.length" class="step-list">
        <div
          v-for="step in steps"
          :key="step.id"
          class="step-item"
          :class="step.status"
        >
          <div class="step-dot"></div>
          <div class="step-content">
            <div class="step-title">
              <span>{{ step.title }}</span>
              <time>{{ step.time }}</time>
            </div>
            <pre v-if="step.detail" class="step-detail">{{ step.detail }}</pre>
          </div>
        </div>
      </div>
      <el-empty v-else description="暂无思考过程" />

      <details v-if="logs" class="raw-log">
        <summary>完整 Agent 日志</summary>
        <pre class="log-block">{{ logs }}</pre>
      </details>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ThinkingStep } from '../types/query'

// 展示折叠后的思考摘要和展开后的完整步骤，查询完成后由父组件控制默认收起。
const props = defineProps<{
  logs: string
  steps: ThinkingStep[]
  loading: boolean
  expanded: boolean
}>()

const emit = defineEmits<{
  (e: 'toggle'): void
}>()

// 卡片右上角的状态说明，避免用户在长查询期间误以为页面卡住。
const statusText = computed(() => {
  if (props.loading) {
    return '正在分析'
  }
  if (props.steps.length) {
    return '已完成'
  }
  return '等待查询'
})

// 折叠时优先展示最新一步，类似“正在做什么”的轻量反馈。
const collapsedText = computed(() => {
  if (props.loading) {
    const latest = props.steps[props.steps.length - 1]
    return latest ? latest.title : '正在准备查询'
  }
  if (props.steps.length) {
    return `已完成 ${props.steps.length} 个步骤，点击展开查看`
  }
  return '提交问题后会显示查询过程'
})
</script>

<style scoped>
.panel-card {
  height: 100%;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.status-text {
  margin-left: 10px;
  color: #5f6f86;
  font-size: 13px;
  font-weight: 400;
}

.collapsed-view {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 42px;
  color: #344255;
}

.pulse {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #8aa0b8;
}

.pulse.active {
  background: #409eff;
  box-shadow: 0 0 0 6px rgba(64, 158, 255, 0.12);
}

.thinking-body {
  display: grid;
  gap: 14px;
}

.step-list {
  display: grid;
  gap: 12px;
  max-height: 360px;
  overflow: auto;
  padding-right: 4px;
}

.step-item {
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr);
  gap: 10px;
}

.step-dot {
  width: 9px;
  height: 9px;
  margin-top: 7px;
  border-radius: 50%;
  background: #93a4b8;
}

.step-item.running .step-dot {
  background: #409eff;
}

.step-item.error .step-dot {
  background: #f56c6c;
}

.step-content {
  min-width: 0;
}

.step-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  color: #253044;
  font-size: 14px;
  font-weight: 700;
}

.step-title time {
  flex: 0 0 auto;
  color: #8a98aa;
  font-size: 12px;
  font-weight: 400;
}

.step-detail {
  margin: 7px 0 0;
  color: #4b5c70;
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.raw-log {
  border-top: 1px solid #edf1f6;
  padding-top: 12px;
}

.raw-log summary {
  cursor: pointer;
  color: #5f6f86;
  font-size: 13px;
}

.log-block {
  max-height: 360px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  color: #344255;
  font-size: 13px;
  line-height: 1.55;
}
</style>
