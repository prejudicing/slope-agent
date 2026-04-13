<template>
  <el-card shadow="never" class="panel-card">
    <template #header>
      <span>生成 SQL</span>
    </template>

    <pre class="code-block">{{ sql || '暂未提取 SQL' }}</pre>
  </el-card>
</template>

<script setup lang="ts">
defineProps<{
  sql: string
}>()
</script>

<style scoped>
.panel-card {
  height: 100%;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
}

.code-block {
  min-height: 120px;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  color: #1d344f;
  font-family: Consolas, Monaco, monospace;
  line-height: 1.6;
}
</style>
