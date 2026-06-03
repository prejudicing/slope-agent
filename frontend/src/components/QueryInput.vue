<template>
  <div class="composer-box">
    <div v-if="isListening" class="voice-panel">
      <div class="voice-main">
        <div class="voice-orb">
          <span class="mic-icon" aria-hidden="true"></span>
        </div>
        <div class="voice-copy">
          <strong>正在听您说</strong>
          <span>{{ voiceDraft || voiceStatusText }}</span>
        </div>
        <div class="voice-wave" aria-hidden="true">
          <i v-for="index in 5" :key="index"></i>
        </div>
      </div>
      <div class="voice-actions">
        <button
          type="button"
          class="voice-action secondary"
          @click.prevent="cancelVoiceInput"
        >
          取消
        </button>
        <button
          type="button"
          class="voice-action primary"
          @click.prevent="finishVoiceInput"
        >
          说完了
        </button>
      </div>
    </div>
    <el-input
      v-model="localQuestion"
      type="textarea"
      :autosize="{ minRows: 1, maxRows: 5 }"
      resize="none"
      placeholder="向高切坡智能助手提问，例如：查看最近有异常的监测记录"
      @keydown.enter.exact.prevent="handleSubmit"
    />
    <div class="composer-actions">
      <span class="hint">Enter 发送，Shift + Enter 换行</span>
      <el-tooltip :content="voiceTip" placement="top">
        <el-button
          class="voice-button"
          :disabled="loading || isListening"
          :loading="isListening"
          aria-label="语音输入"
          @click="startVoiceInput"
        >
          <span class="mic-icon" aria-hidden="true"></span>
        </el-button>
      </el-tooltip>
      <el-button :disabled="loading" @click="clearInput">清空</el-button>
      <el-button type="primary" :loading="loading" @click="handleSubmit">发送</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Capacitor, type PluginListenerHandle } from '@capacitor/core'
import { SpeechRecognition } from '@capacitor-community/speech-recognition'
import { VoiceRecorder } from 'capacitor-voice-recorder'
import { ElMessage } from 'element-plus'
import { computed, ref, watch } from 'vue'
import { transcribeAudio } from '../api/query'

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
const voiceDraft = ref('')
const voiceStatusText = ref('请说出要查询的问题')
const voiceFinishing = ref(false)
let activeWebRecognition: any = null
let nativeStateListener: PluginListenerHandle | null = null
let nativeSessionId = 0
let nativeStopping = false
let nativeStartPromise: Promise<{ matches?: string[] }> | null = null
let nativeRecorderActive = false
const webSpeechSupported =
  typeof window !== 'undefined' && Boolean((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition)
const isNativeApp = Capacitor.isNativePlatform()
const isSecureBrowserContext =
  typeof window !== 'undefined' &&
  (window.isSecureContext || ['localhost', '127.0.0.1'].includes(window.location.hostname))

const speechSupported = computed(() => isNativeApp || (webSpeechSupported && isSecureBrowserContext))
const voiceTip = computed(() => {
  if (isNativeApp) return '语音输入'
  if (!webSpeechSupported) return '当前浏览器不支持语音输入'
  if (!isSecureBrowserContext) return '手机浏览器需使用 HTTPS 或安装 APK 后才能使用语音'
  return '语音输入'
})

watch(
  () => props.question,
  (val) => {
    localQuestion.value = val
  },
)

watch(localQuestion, (val) => {
  emit('update:question', val)
})

const clearInput = () => {
  localQuestion.value = ''
}

const handleSubmit = () => {
  emit('submit')
}

const startVoiceInput = async () => {
  if (isListening.value) {
    return
  }
  if (!speechSupported.value) {
    ElMessage.warning(voiceTip.value)
    return
  }
  if (isNativeApp) {
    await startNativeVoiceInput()
    return
  }
  startWebVoiceInput()
}

const startNativeVoiceInput = async () => {
  try {
    nativeSessionId += 1
    const sessionId = nativeSessionId
    isListening.value = true
    voiceFinishing.value = false
    voiceDraft.value = ''
    voiceStatusText.value = '正在准备语音输入'
    await cleanupNativeListeners()
    await stopNativeVoiceSafely(true)
    const canRecord = await VoiceRecorder.canDeviceVoiceRecord()
    if (!canRecord.value) {
      ElMessage.warning('当前设备不支持语音输入')
      isListening.value = false
      return
    }
    const hasPermission = await VoiceRecorder.hasAudioRecordingPermission()
    if (!hasPermission.value) {
      const permission = await VoiceRecorder.requestAudioRecordingPermission()
      if (!permission.value) {
        ElMessage.warning('请允许麦克风权限后再使用语音输入')
        isListening.value = false
        return
      }
    }
    if (sessionId !== nativeSessionId) {
      return
    }
    await VoiceRecorder.startRecording()
    nativeRecorderActive = true
    voiceStatusText.value = '请说出要查询的问题'
  } catch (error: any) {
    console.warn('voice recorder start failed, fallback to speech recognition', error)
    nativeRecorderActive = false
    await startNativeSpeechRecognition()
  }
}

const startNativeSpeechRecognition = async () => {
  try {
    nativeSessionId += 1
    const sessionId = nativeSessionId
    nativeStopping = false
    isListening.value = true
    voiceDraft.value = ''
    voiceStatusText.value = '正在准备语音识别'
    await cleanupNativeListeners()
    await Promise.race([
      SpeechRecognition.stop().catch(() => undefined),
      wait(300),
    ])
    if (sessionId !== nativeSessionId) {
      return
    }
    const available = await SpeechRecognition.available()
    if (!available.available) {
      ElMessage.warning('当前设备未开启语音识别服务')
      isListening.value = false
      return
    }
    const permission = await SpeechRecognition.requestPermissions()
    if (permission.speechRecognition !== 'granted') {
      ElMessage.warning('请允许麦克风权限后再使用语音输入')
      isListening.value = false
      return
    }
    await cleanupNativeListeners()
    nativeStateListener = await SpeechRecognition.addListener('listeningState', (data) => {
      if (sessionId !== nativeSessionId) {
        return
      }
      if (data.status === 'stopped' && !nativeStopping) {
        voiceStatusText.value = voiceDraft.value ? '已识别语音内容' : '正在整理识别结果'
        window.setTimeout(() => {
          if (sessionId === nativeSessionId) {
            isListening.value = false
            void cleanupNativeListeners()
          }
        }, 500)
      }
    })
    voiceStatusText.value = '请说出要查询的问题'
    nativeStartPromise = SpeechRecognition.start({
      language: 'zh-CN',
      maxResults: 1,
      prompt: '请说出要查询的问题',
      popup: false,
      partialResults: false,
    })
    void nativeStartPromise
      .then((result) => {
        if (sessionId !== nativeSessionId) {
          return
        }
        const text = normalizeVoiceText(result?.matches?.[0])
        if (text) {
          applyVoiceText(text)
          voiceStatusText.value = '已识别语音内容'
        } else {
          voiceStatusText.value = '未识别到内容，请重试'
        }
      })
      .catch((error) => {
        if (sessionId !== nativeSessionId) {
          return
        }
        voiceStatusText.value = '未识别到内容，请重试'
        console.warn('speech recognition result failed', error)
      })
  } catch (error: any) {
    ElMessage.warning(error?.message || '语音输入启动失败')
    isListening.value = false
    await cleanupNativeListeners()
  }
}

const startWebVoiceInput = () => {
  const Recognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  const recognition = new Recognition()
  activeWebRecognition = recognition
  recognition.lang = 'zh-CN'
  recognition.interimResults = true
  recognition.continuous = false
  voiceDraft.value = ''
  isListening.value = true
  recognition.onresult = (event: any) => {
    const results = Array.from(event?.results || []) as any[]
    const text = results.map((item) => item?.[0]?.transcript || '').join('').trim()
    if (text) {
      voiceDraft.value = text
      localQuestion.value = text
    }
  }
  recognition.onerror = (event: any) => {
    ElMessage.warning(event?.error === 'not-allowed' ? '请允许麦克风权限后再使用语音输入' : '语音输入启动失败')
    isListening.value = false
  }
  recognition.onend = () => {
    isListening.value = false
    activeWebRecognition = null
  }
  recognition.start()
}

const finishVoiceInput = async () => {
  if (voiceFinishing.value) {
    return
  }
  voiceFinishing.value = true
  if (voiceDraft.value) {
    localQuestion.value = voiceDraft.value
  }
  if (isNativeApp) {
    if (nativeRecorderActive) {
      void finishNativeRecorderSafely()
    } else {
      isListening.value = false
      void finishNativeVoiceSafely()
    }
  } else if (activeWebRecognition) {
    isListening.value = false
    activeWebRecognition.stop()
  }
}

const cancelVoiceInput = async () => {
  if (voiceFinishing.value) {
    return
  }
  voiceDraft.value = ''
  isListening.value = false
  voiceFinishing.value = false
  if (isNativeApp) {
    nativeSessionId += 1
    if (nativeRecorderActive) {
      void stopNativeRecorderSafely()
    } else {
      void stopNativeVoiceSafely(true)
    }
  } else if (activeWebRecognition) {
    activeWebRecognition.abort?.()
  }
}

async function cleanupNativeListeners() {
  await nativeStateListener?.remove().catch(() => undefined)
  nativeStateListener = null
}

async function finishNativeVoiceSafely() {
  nativeStopping = true
  try {
    await Promise.race([
      SpeechRecognition.stop().catch(() => undefined),
      wait(800),
    ])
    const result = await Promise.race([
      nativeStartPromise?.catch(() => undefined),
      wait(1800).then(() => undefined),
    ])
    const text = normalizeVoiceText(result?.matches?.[0])
    if (text) {
      applyVoiceText(text)
    } else if (!voiceDraft.value) {
      ElMessage.warning('未识别到语音内容，请再试一次')
    }
  } finally {
    nativeStartPromise = null
    await cleanupNativeListeners()
    nativeStopping = false
  }
}

async function finishNativeRecorderSafely() {
  try {
    voiceStatusText.value = '正在识别语音内容'
    console.log('voice recorder stopping')
    const result = await VoiceRecorder.stopRecording()
    nativeRecorderActive = false
    const audioBase64 = result.value.recordDataBase64 || ''
    console.log('voice recorder stopped', {
      duration: result.value.msDuration,
      mimeType: result.value.mimeType,
      hasAudio: Boolean(audioBase64),
      audioLength: audioBase64.length,
    })
    if (!audioBase64 || result.value.msDuration < 400) {
      ElMessage.warning('录音时间较短，请再试一次')
      return
    }
    console.log('voice recorder transcribing')
    const response = await transcribeAudio(
      audioBase64,
      result.value.mimeType || 'audio/aac',
      `query_audio_${Date.now()}.m4a`,
    )
    console.log('voice recorder transcribed', {
      hasText: Boolean(response.text),
      error: response.error || '',
    })
    const text = normalizeVoiceText(response.text)
    if (text) {
      applyVoiceText(text)
      voiceStatusText.value = '已识别语音内容'
    } else {
      ElMessage.warning(response.error || '未识别到语音内容，请再试一次')
    }
  } catch (error: any) {
    console.warn('voice recorder finish failed', error)
    ElMessage.warning(error?.message || '语音识别失败，请再试一次')
  } finally {
    isListening.value = false
    nativeRecorderActive = false
    voiceFinishing.value = false
  }
}

async function stopNativeRecorderSafely() {
  try {
    await VoiceRecorder.stopRecording().catch(() => undefined)
  } finally {
    nativeRecorderActive = false
  }
}

async function stopNativeVoiceSafely(clearImmediately = false) {
  nativeStopping = true
  try {
    await Promise.race([
      SpeechRecognition.stop().catch(() => undefined),
      new Promise((resolve) => window.setTimeout(resolve, 800)),
    ])
    if (!clearImmediately) {
      await wait(500)
    }
  } finally {
    nativeStartPromise = null
    await cleanupNativeListeners()
    nativeStopping = false
  }
}

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function normalizeVoiceText(text?: string) {
  return convertTraditionalToSimplified((text || '').replace(/\s+/g, '').trim())
}

function applyVoiceText(text: string) {
  voiceDraft.value = text
  localQuestion.value = text
}

function convertTraditionalToSimplified(text: string) {
  const map: Record<string, string> = {
    臺: '台',
    颱: '台',
    灣: '湾',
    點: '点',
    關: '关',
    注: '注',
    風: '风',
    險: '险',
    區: '区',
    縣: '县',
    鄉: '乡',
    鎮: '镇',
    村: '村',
    問: '问',
    題: '题',
    查: '查',
    詢: '询',
    統: '统',
    計: '计',
    監: '监',
    測: '测',
    專: '专',
    業: '业',
    變: '变',
    化: '化',
    量: '量',
    較: '较',
    大: '大',
    近: '近',
    期: '期',
    哪: '哪',
    些: '些',
    值: '值',
    得: '得',
    重: '重',
    截: '截',
    緩: '缓',
    慢: '慢',
    明: '明',
    顯: '显',
    穩: '稳',
    定: '定',
    評: '评',
    價: '价',
    預: '预',
    告: '告',
    警: '警',
    裂: '裂',
    縫: '缝',
    落: '落',
    石: '石',
    擋: '挡',
    牆: '墙',
    道: '道',
    路: '路',
    現: '现',
    場: '场',
    照: '照',
    片: '片',
    異: '异',
    常: '常',
    群: '群',
    防: '防',
    數: '数',
    據: '据',
    簡: '简',
    報: '报',
    會: '会',
    話: '话',
    導: '导',
    出: '出',
    載: '载',
    处: '处',
    處: '处',
    聯: '联',
    繫: '系',
    電: '电',
    人: '人',
    員: '员',
    狀: '状',
    態: '态',
    況: '况',
    圖: '图',
    表: '表',
    軸: '轴',
    累: '累',
    積: '积',
    年: '年',
    月: '月',
    度: '度',
    位: '位',
    移: '移',
    高: '高',
    切: '切',
    坡: '坡',
  }
  let normalized = text.replace(/[^\x00-\x7F]/g, (char) => map[char] || char)
  const phraseReplacements: Array<[string, string]> = [
    ['專業監測', '专业监测'],
    ['位移變化量', '位移变化量'],
    ['高切破', '高切坡'],
    ['高清坡', '高切坡'],
    ['高青坡', '高切坡'],
    ['高边坡', '高切坡'],
    ['群测群房', '群测群防'],
    ['群策群防', '群测群防'],
    ['专页监测', '专业监测'],
    ['其哪些', '哪些'],
  ]
  phraseReplacements.forEach(([from, to]) => {
    normalized = normalized.replaceAll(from, to)
  })
  return normalized
}
</script>

<style scoped>
.composer-box {
  display: grid;
  gap: 10px;
  max-width: 980px;
  margin: 0 auto;
  border: 1px solid #d9e3f5;
  border-radius: 8px;
  background: #fff;
  padding: 12px;
  box-shadow: 0 12px 30px rgba(23, 35, 58, 0.08);
}

.voice-panel {
  display: grid;
  gap: 12px;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: linear-gradient(180deg, #f8fbff 0%, #eef6ff 100%);
  padding: 12px;
}

.voice-main {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
}

.voice-orb {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: 50%;
  color: #fff;
  background: #1d4ed8;
  box-shadow: 0 0 0 8px rgba(37, 99, 235, 0.12);
}

.voice-copy {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.voice-copy strong {
  color: #0f172a;
  font-size: 15px;
}

.voice-copy span {
  overflow: hidden;
  color: #475467;
  font-size: 13px;
  line-height: 1.5;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.voice-wave {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 28px;
}

.voice-wave i {
  width: 4px;
  height: 10px;
  border-radius: 8px;
  background: #2563eb;
  animation: voice-wave 0.9s ease-in-out infinite;
}

.voice-wave i:nth-child(2) {
  animation-delay: 0.1s;
}

.voice-wave i:nth-child(3) {
  animation-delay: 0.2s;
}

.voice-wave i:nth-child(4) {
  animation-delay: 0.3s;
}

.voice-wave i:nth-child(5) {
  animation-delay: 0.4s;
}

.voice-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.voice-action {
  min-height: 34px;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: #fff;
  color: #1d4ed8;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  padding: 6px 14px;
  touch-action: manipulation;
}

.voice-action.primary {
  border-color: #2563eb;
  background: #2563eb;
  color: #fff;
}

.voice-action:active {
  transform: translateY(1px);
}

@keyframes voice-wave {
  0%,
  100% {
    height: 8px;
    opacity: 0.45;
  }
  50% {
    height: 26px;
    opacity: 1;
  }
}

.composer-box :deep(.el-textarea__inner) {
  min-height: 46px !important;
  border: 0;
  box-shadow: none;
  color: #1f2937;
  font-size: 15px;
  line-height: 1.6;
  padding: 6px 4px;
}

.composer-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.hint {
  margin-right: auto;
  color: #98a2b3;
  font-size: 12px;
}

.voice-button {
  width: 34px;
  padding: 8px;
}

.mic-icon {
  position: relative;
  display: inline-block;
  width: 12px;
  height: 18px;
}

.mic-icon::before {
  position: absolute;
  left: 3px;
  top: 0;
  width: 6px;
  height: 10px;
  border: 2px solid currentColor;
  border-radius: 6px;
  content: '';
}

.mic-icon::after {
  position: absolute;
  left: 1px;
  top: 8px;
  width: 10px;
  height: 8px;
  border: 2px solid currentColor;
  border-top: 0;
  border-radius: 0 0 8px 8px;
  box-shadow: 0 7px 0 -5px currentColor;
  content: '';
}

@media (max-width: 640px) {
  .composer-box {
    padding: 10px;
  }

  .composer-actions {
    display: grid;
    grid-template-columns: 1fr auto auto auto;
    gap: 8px;
  }

  .hint {
    grid-column: 1 / -1;
    margin-right: 0;
  }

  .composer-actions :deep(.el-button) {
    min-width: 0;
    margin-left: 0;
    padding: 8px 10px;
  }

  .voice-button {
    width: 34px;
    padding: 8px;
  }

  .voice-main {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .voice-wave {
    grid-column: 1 / -1;
    justify-content: center;
  }

  .voice-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
}
</style>

