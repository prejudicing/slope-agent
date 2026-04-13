<template>
  <el-card shadow="never" class="panel-card">
    <template #header>
      <span>Agent 日志</span>
    </template>

    <pre class="log-block">{{ logs || '暂无日志' }}</pre>
  </el-card>
</template>

<script setup lang="ts">
defineProps<{
  logs: string
}>()
</script>

<style scoped>
.panel-card {
  height: 100%;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
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
