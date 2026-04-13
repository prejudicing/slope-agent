<template>
  <div class="query-input">
    <el-input
      v-model="localQuestion"
      type="textarea"
      :rows="4"
      placeholder="请输入你的问题，例如：统计各区县高切坡数量，或查询最近有异常的巡查记录"
    />
    <div class="query-actions">
      <el-button type="primary" :loading="loading" @click="handleSubmit">
        查询
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

// 使用本地副本承接 v-model，避免父组件重置问题时 textarea 状态不同步。
const props = defineProps<{
  question: string
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'update:question', value: string): void
  (e: 'submit'): void
}>()

const localQuestion = ref(props.question)

// 父组件清空或恢复问题时，同步到输入框。
watch(
  () => props.question,
  (val) => {
    localQuestion.value = val
  }
)

// 输入框变化时，向父组件同步 question。
watch(localQuestion, (val) => {
  emit('update:question', val)
})

const handleSubmit = () => {
  // 具体校验和请求逻辑在 App.vue 中集中处理。
  emit('submit')
}
</script>

<style scoped>
.query-input {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.query-actions {
  display: flex;
  justify-content: flex-end;
}

.query-input :deep(.el-textarea__inner) {
  border-radius: 8px;
  line-height: 1.6;
}
</style>
