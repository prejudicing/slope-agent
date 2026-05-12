<template>
  <el-card shadow="never" class="panel-card">
    <template #header>
      <span>查询总结</span>
    </template>

    <pre class="summary-block">{{ summary || '暂无总结' }}</pre>
    <div v-if="summary.trim()" class="speech-inline">
      <SpeechPlayer :summary="summary" compact />
    </div>
  </el-card>
</template>

<script setup lang="ts">
import SpeechPlayer from './SpeechPlayer.vue'

defineProps<{
  summary: string
}>()
</script>

<style scoped>
.panel-card {
  height: 100%;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
}

.summary-block {
  min-height: 120px;
  margin: 0;
  color: #253044;
  font-family: Arial, Helvetica, sans-serif;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.speech-inline {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #edf2f7;
}
</style>
