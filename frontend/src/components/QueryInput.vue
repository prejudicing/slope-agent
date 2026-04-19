<template>
  <div class="query-input">
    <el-input
      v-model="localQuestion"
      type="textarea"
      :rows="4"
      placeholder="请输入你的问题，例如：统计各区县高切坡数量，或查询最近有异常的巡查记录"
    />
    <div class="query-actions">
      <span v-if="speechHint" class="speech-hint">{{ speechHint }}</span>
      <el-button
        :type="isListening ? 'danger' : 'default'"
        :disabled="loading"
        @click="toggleSpeechInput"
      >
        {{ isListening ? '停止语音' : '中文语音输入' }}
      </el-button>
      <el-button type="primary" :loading="loading" @click="handleSubmit">
        查询
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

interface SpeechRecognitionEventLike {
  resultIndex: number
  results: {
    length: number
    [index: number]: {
      isFinal: boolean
      [index: number]: {
        transcript: string
      }
    }
  }
}

interface SpeechRecognitionErrorEventLike {
  error: string
}

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
const isListening = ref(false)
const speechHint = ref('')
const recognition = ref<SpeechRecognitionLike | null>(null)
const speechBaseText = ref('')
const finalSpeechText = ref('')

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

const getSpeechRecognition = (): SpeechRecognitionConstructor | null => {
  const speechWindow = window as Window & {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }
  return speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition || null
}

const isSpeechSecureOrigin = () => {
  return (
    window.isSecureContext ||
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1'
  )
}

const composeSpeechText = (interimText = '') => {
  const parts = [speechBaseText.value, finalSpeechText.value, interimText]
    .map((item) => item.trim())
    .filter(Boolean)
  localQuestion.value = parts.join(' ')
}

const stopSpeechInput = () => {
  if (!recognition.value) {
    return
  }
  recognition.value.stop()
  recognition.value = null
  isListening.value = false
  speechHint.value = finalSpeechText.value ? '语音已写入输入框' : ''
}

const startSpeechInput = () => {
  if (!isSpeechSecureOrigin()) {
    speechHint.value = '语音输入需要 HTTPS 或 localhost'
    ElMessage.warning('浏览器通常要求 HTTPS 或 localhost 才能使用麦克风语音识别')
    return
  }

  const SpeechRecognition = getSpeechRecognition()
  if (!SpeechRecognition) {
    speechHint.value = '当前浏览器不支持语音识别'
    ElMessage.warning('当前浏览器不支持语音识别，建议使用 Chrome 或 Edge')
    return
  }

  const instance = new SpeechRecognition()
  instance.lang = 'zh-CN'
  instance.continuous = true
  instance.interimResults = true
  instance.maxAlternatives = 1

  speechBaseText.value = localQuestion.value.trim()
  finalSpeechText.value = ''
  speechHint.value = '正在听，请说出你的查询问题'

  instance.onresult = (event) => {
    let interimText = ''

    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const item = event.results[index]
      const transcript = item[0]?.transcript || ''
      if (item.isFinal) {
        finalSpeechText.value = `${finalSpeechText.value}${transcript}`
      } else {
        interimText = `${interimText}${transcript}`
      }
    }

    composeSpeechText(interimText)
  }

  instance.onerror = (event) => {
    isListening.value = false
    recognition.value = null
    speechHint.value = '语音识别失败，请检查麦克风权限'
    if (event.error !== 'no-speech') {
      ElMessage.warning(`语音识别失败：${event.error}`)
    }
  }

  instance.onend = () => {
    isListening.value = false
    recognition.value = null
    if (!speechHint.value.includes('失败')) {
      speechHint.value = finalSpeechText.value ? '语音已写入输入框' : ''
    }
  }

  recognition.value = instance
  isListening.value = true

  try {
    instance.start()
  } catch {
    isListening.value = false
    recognition.value = null
    speechHint.value = '语音识别启动失败'
    ElMessage.warning('语音识别启动失败，请稍后重试')
  }
}

const toggleSpeechInput = () => {
  if (isListening.value) {
    stopSpeechInput()
    return
  }
  startSpeechInput()
}

const handleSubmit = () => {
  if (isListening.value) {
    stopSpeechInput()
  }
  // 具体校验和请求逻辑在 App.vue 中集中处理。
  emit('submit')
}

onBeforeUnmount(() => {
  if (recognition.value) {
    recognition.value.abort()
  }
})
</script>

<style scoped>
.query-input {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.query-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: flex-end;
}

.speech-hint {
  min-width: 0;
  color: #5f6f86;
  font-size: 13px;
  overflow-wrap: anywhere;
}

.query-input :deep(.el-textarea__inner) {
  border-radius: 8px;
  line-height: 1.6;
}

@media (max-width: 640px) {
  .query-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .query-actions :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }
}
</style>
