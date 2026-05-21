<template>
  <div class="query-input">
    <div v-if="speechHint" class="speech-hint">{{ speechHint }}</div>
    <div class="composer-row">
      <button
        type="button"
        class="new-chat-button"
        :disabled="loading || isListening || isTranscribing"
        title="上下文已清除，开始新的对话"
        @click="emit('clear')"
      >
        <span class="new-chat-glyph" aria-hidden="true">
          <span class="bubble-outline"></span>
          <span class="bubble-plus"></span>
        </span>
      </button>

      <div class="input-shell">
        <el-input
          v-model="localQuestion"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 5 }"
          resize="none"
          :placeholder="
            placeholder ||
            '请输入你的问题，例如：统计各区县高切坡数量，或查询最近有异常的巡查记录'
          "
          @keydown.enter.exact.prevent="handleSubmit"
        />

        <button
          type="button"
          class="action-button"
          :class="{ listening: isListening, sending: hasQuestion }"
          :disabled="loading || isTranscribing"
          @click="hasQuestion ? handleSubmit() : toggleSpeechInput()"
        >
          <el-icon v-if="hasQuestion"><Promotion /></el-icon>
          <el-icon v-else><Microphone /></el-icon>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { Microphone, Promotion } from '@element-plus/icons-vue'
import { Capacitor } from '@capacitor/core'
import { VoiceRecorder } from 'capacitor-voice-recorder'
import { ElMessage } from 'element-plus'
import { transcribeAudio } from '../api/query'

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
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: 'update:question', value: string): void
  (e: 'submit'): void
  (e: 'clear'): void
}>()

const localQuestion = ref(props.question)
const isListening = ref(false)
const isTranscribing = ref(false)
const speechHint = ref('')
const hasQuestion = ref(false)
const recognition = ref<SpeechRecognitionLike | null>(null)
const browserRecorder = ref<MediaRecorder | null>(null)
const browserStream = ref<MediaStream | null>(null)
const browserAudioChunks = ref<Blob[]>([])
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
  hasQuestion.value = Boolean(val.trim())
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

const cleanupBrowserRecorder = () => {
  browserRecorder.value = null
  browserAudioChunks.value = []
  if (browserStream.value) {
    browserStream.value.getTracks().forEach((track) => track.stop())
    browserStream.value = null
  }
}

type BrowserRecordingStartResult = 'started' | 'blocked' | 'fallback'

const blobToBase64 = (blob: Blob) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onloadend = () => {
      const result = String(reader.result || '')
      const base64 = result.includes(',') ? result.split(',')[1] : result
      resolve(base64)
    }
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })

const buildAudioFilename = (mimeType: string) => {
  const suffixMap: Record<string, string> = {
    'audio/aac': 'aac',
    'audio/mp4': 'm4a',
    'audio/mpeg': 'mp3',
    'audio/wav': 'wav',
    'audio/webm': 'webm',
    'audio/ogg': 'ogg',
  }
  const normalizedMimeType = mimeType.split(';')[0].trim().toLowerCase()
  const suffix = suffixMap[normalizedMimeType] || 'm4a'
  return `query_audio.${suffix}`
}

const stopNativeSpeechInput = async () => {
  isListening.value = false

  let recording
  try {
    recording = await VoiceRecorder.stopRecording()
  } catch (error) {
    speechHint.value = '停止录音失败'
    ElMessage.warning('停止录音失败，请重新尝试')
    return
  }

  const recordDataBase64 = recording.value.recordDataBase64 || ''
  const mimeType = recording.value.mimeType || 'audio/mp4'

  if (!recordDataBase64) {
    speechHint.value = '录音内容为空，请重新录制'
    ElMessage.warning('录音内容为空，请重新录制')
    return
  }

  isTranscribing.value = true
  speechHint.value = '正在将录音转成文字...'

  try {
    const result = await transcribeAudio(
      recordDataBase64,
      mimeType,
      buildAudioFilename(mimeType)
    )
    if (result.error) {
      throw new Error(result.error)
    }

    finalSpeechText.value = (result.text || '').trim()
    composeSpeechText()
    speechHint.value = finalSpeechText.value ? '语音已写入输入框' : '未识别到有效语音'
  } catch (error: any) {
    speechHint.value = '语音转写失败'
    ElMessage.warning(error?.message || '语音转写失败，请稍后重试')
  } finally {
    isTranscribing.value = false
  }
}

const ensureNativeSpeechPermission = async () => {
  const permission = await VoiceRecorder.hasAudioRecordingPermission()
  if (permission.value) {
    return true
  }

  const requested = await VoiceRecorder.requestAudioRecordingPermission()
  return requested.value
}

const startNativeSpeechInput = async () => {
  const availability = await VoiceRecorder.canDeviceVoiceRecord()
  if (!availability.value) {
    speechHint.value = '当前设备不支持原生录音'
    ElMessage.warning('当前设备不支持原生录音')
    return
  }

  const hasPermission = await ensureNativeSpeechPermission()
  if (!hasPermission) {
    speechHint.value = '未授予麦克风权限'
    ElMessage.warning('请允许麦克风权限后再使用语音输入')
    return
  }

  speechBaseText.value = localQuestion.value.trim()
  finalSpeechText.value = ''
  speechHint.value = '正在录音，请说出你的查询问题'

  try {
    await VoiceRecorder.startRecording()
    isListening.value = true
  } catch {
    isListening.value = false
    speechHint.value = '原生录音启动失败'
    ElMessage.warning('原生录音启动失败，请稍后重试')
  }
}

const stopBrowserSpeechInput = async () => {
  const recorder = browserRecorder.value
  if (!recorder) {
    if (recognition.value) {
      recognition.value.stop()
      recognition.value = null
    }
    isListening.value = false
    return
  }

  isListening.value = false
  speechHint.value = '正在将录音转成文字...'

  const stopPromise = new Promise<void>((resolve) => {
    recorder.onstop = async () => {
      try {
        const mimeType = recorder.mimeType || browserAudioChunks.value[0]?.type || 'audio/webm'
        const blob = new Blob(browserAudioChunks.value, { type: mimeType })
        if (!blob.size) {
          speechHint.value = '录音内容为空，请重新录制'
          ElMessage.warning('录音内容为空，请重新录制')
          return
        }

        isTranscribing.value = true
        const audioBase64 = await blobToBase64(blob)
        const result = await transcribeAudio(
          audioBase64,
          mimeType,
          buildAudioFilename(mimeType)
        )
        if (result.error) {
          throw new Error(result.error)
        }

        finalSpeechText.value = (result.text || '').trim()
        composeSpeechText()
        speechHint.value = finalSpeechText.value ? '语音已写入输入框' : '未识别到有效语音'
      } catch (error: any) {
        speechHint.value = '语音转写失败'
        ElMessage.warning(error?.message || '语音转写失败，请稍后重试')
      } finally {
        isTranscribing.value = false
        cleanupBrowserRecorder()
        resolve()
      }
    }
  })

  recorder.stop()
  await stopPromise
}

const startBrowserRecordingInput = async (): Promise<BrowserRecordingStartResult> => {
  if (!isSpeechSecureOrigin()) {
    speechHint.value = '当前页面不是安全地址，浏览器通常不会开放麦克风'
    ElMessage.warning('请改用 HTTPS 地址或 localhost 后再使用浏览器语音输入')
    return 'blocked'
  }

  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    return 'fallback'
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    browserStream.value = stream
    browserAudioChunks.value = []

    const mimeTypes = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/mp4',
      'audio/ogg;codecs=opus',
    ]
    const selectedMimeType =
      mimeTypes.find((mimeType) => MediaRecorder.isTypeSupported?.(mimeType)) || ''

    const recorder = selectedMimeType
      ? new MediaRecorder(stream, { mimeType: selectedMimeType })
      : new MediaRecorder(stream)

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        browserAudioChunks.value.push(event.data)
      }
    }

    speechBaseText.value = localQuestion.value.trim()
    finalSpeechText.value = ''
    speechHint.value = '正在录音，请说出你的查询问题'
    browserRecorder.value = recorder
    recorder.start()
    isListening.value = true
    return 'started'
  } catch {
    cleanupBrowserRecorder()
    isListening.value = false
    speechHint.value = '浏览器录音启动失败'
    ElMessage.warning('浏览器录音启动失败，请检查麦克风权限')
    return 'blocked'
  }
}

const stopSpeechInput = async () => {
  if (Capacitor.isNativePlatform()) {
    await stopNativeSpeechInput()
    return
  }
  if (browserRecorder.value) {
    await stopBrowserSpeechInput()
    return
  }
  if (!recognition.value) {
    return
  }
  recognition.value.stop()
  recognition.value = null
  isListening.value = false
  speechHint.value = finalSpeechText.value ? '语音已写入输入框' : ''
}

const startSpeechInput = async () => {
  if (Capacitor.isNativePlatform()) {
    await startNativeSpeechInput()
    return
  }

  const browserRecordingState = await startBrowserRecordingInput()
  if (browserRecordingState === 'started') {
    return
  }
  if (browserRecordingState === 'blocked') {
    return
  }

  if (!isSpeechSecureOrigin()) {
    speechHint.value = '当前页面不是安全地址，浏览器通常不会开放麦克风'
    ElMessage.warning('请改用 HTTPS 地址或 localhost 后再使用浏览器语音输入')
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

const toggleSpeechInput = async () => {
  if (isListening.value) {
    await stopSpeechInput()
    return
  }
  await startSpeechInput()
}

const handleSubmit = async () => {
  if (isListening.value) {
    await stopSpeechInput()
  }
  if (isTranscribing.value) {
    ElMessage.info('语音仍在转写中，请稍候')
    return
  }
  // 具体校验和请求逻辑在 App.vue 中集中处理。
  emit('submit')
}

onBeforeUnmount(() => {
  if (browserRecorder.value && browserRecorder.value.state !== 'inactive') {
    browserRecorder.value.stop()
  }
  cleanupBrowserRecorder()
  if (recognition.value) {
    recognition.value.abort()
  }
  if (Capacitor.isNativePlatform() && isListening.value) {
    void VoiceRecorder.stopRecording().catch(() => {})
  }
})
</script>

<style scoped>
.query-input {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.composer-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.speech-hint {
  color: #5b6f69;
  font-size: 12px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.new-chat-button {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 48px;
  height: 48px;
  border: 1px solid #d8d9df;
  border-radius: 999px;
  background: #fff;
  color: #7c7f87;
  cursor: pointer;
  font-size: 22px;
}

.new-chat-button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.new-chat-glyph {
  position: relative;
  display: block;
  width: 22px;
  height: 22px;
}

.bubble-outline {
  position: absolute;
  top: 1px;
  left: 2px;
  width: 16px;
  height: 13px;
  border: 2px solid currentColor;
  border-radius: 6px;
}

.bubble-outline::after {
  content: '';
  position: absolute;
  bottom: -5px;
  left: 2px;
  width: 7px;
  height: 7px;
  border-bottom: 2px solid currentColor;
  border-left: 2px solid currentColor;
  transform: skewX(-28deg);
}

.bubble-plus {
  position: absolute;
  right: 0;
  bottom: 1px;
  width: 9px;
  height: 9px;
}

.bubble-plus::before,
.bubble-plus::after {
  content: '';
  position: absolute;
  background: currentColor;
  border-radius: 999px;
}

.bubble-plus::before {
  top: 4px;
  left: 1px;
  width: 7px;
  height: 2px;
}

.bubble-plus::after {
  top: 1px;
  left: 4px;
  width: 2px;
  height: 7px;
}

.input-shell {
  position: relative;
  flex: 1 1 auto;
  min-width: 0;
}

.query-input :deep(.el-textarea__inner) {
  min-height: 56px !important;
  padding: 16px 68px 16px 22px;
  border: 1px solid #d8d9df;
  border-radius: 999px;
  box-shadow: none;
  color: #1f1f1f;
  font-size: 15px;
  line-height: 1.6;
}

.query-input :deep(.el-textarea__inner:focus) {
  border-color: #6f63ff;
}

.action-button {
  position: absolute;
  top: 50%;
  right: 12px;
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: #3b3b3b;
  cursor: pointer;
  transform: translateY(-50%);
  font-size: 22px;
}

.action-button.sending {
  background: #5e63ff;
  color: #fff;
}

.action-button.listening {
  color: #d9534f;
}

.action-button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

@media (max-width: 640px) {
  .composer-row {
    gap: 10px;
  }
}
</style>
