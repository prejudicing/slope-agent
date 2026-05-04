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
        :disabled="loading || isTranscribing"
        @click="toggleSpeechInput"
      >
        {{ isListening ? '停止录音' : '中文语音输入' }}
      </el-button>
      <el-button type="primary" :loading="loading" @click="handleSubmit">
        查询
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
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
}>()

const emit = defineEmits<{
  (e: 'update:question', value: string): void
  (e: 'submit'): void
}>()

const localQuestion = ref(props.question)
const isListening = ref(false)
const isTranscribing = ref(false)
const speechHint = ref('')
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

const startBrowserRecordingInput = async () => {
  if (!isSpeechSecureOrigin()) {
    speechHint.value = '语音输入需要 HTTPS 或 localhost'
    ElMessage.warning('浏览器录音通常要求 HTTPS 或 localhost')
    return
  }

  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    speechHint.value = '当前浏览器不支持录音上传转写'
    ElMessage.warning('当前浏览器不支持录音上传转写')
    return
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
  } catch {
    cleanupBrowserRecorder()
    isListening.value = false
    speechHint.value = '浏览器录音启动失败'
    ElMessage.warning('浏览器录音启动失败，请检查麦克风权限')
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

  await startBrowserRecordingInput()
  if (browserRecorder.value) {
    return
  }

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
