<template>
  <div :class="['speech-body', { compact }]">
    <div v-if="!compact" class="speech-preview-wrap">
      <p class="speech-preview">{{ previewText }}</p>
    </div>
    <div class="speech-actions">
      <span class="status-text">{{ statusText }}</span>
      <el-button type="primary" :disabled="!canSpeak" @click="startSpeaking">
        开始播报
      </el-button>
      <el-button :disabled="!isSpeaking || isPaused" @click="pauseSpeaking">
        暂停
      </el-button>
      <el-button :disabled="!isPaused" @click="resumeSpeaking">
        继续
      </el-button>
      <el-button :disabled="!isSpeaking && !isPaused" @click="stopSpeaking">
        停止
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { PluginListenerHandle } from '@capacitor/core'
import { Capacitor } from '@capacitor/core'
import { ElMessage } from 'element-plus'
import { NativeTtsPlayer } from '../plugins/nativeTtsPlayer'

const props = withDefaults(
  defineProps<{
    summary: string
    compact?: boolean
  }>(),
  {
    compact: false,
  }
)

const isSpeaking = ref(false)
const isPaused = ref(false)
const nativeTtsAvailable = ref(false)
const nativeListener = ref<PluginListenerHandle | null>(null)
const browserUtterance = ref<SpeechSynthesisUtterance | null>(null)
const ignoreBrowserCancelError = ref(false)
const isNativePlatform = Capacitor.isNativePlatform()

const buildSpeechText = () => props.summary.trim()

const canSpeak = computed(() => {
  if (!buildSpeechText()) {
    return false
  }
  return isNativePlatform ? nativeTtsAvailable.value : 'speechSynthesis' in window
})

const statusText = computed(() => {
  if (isNativePlatform && !nativeTtsAvailable.value) {
    return '原生播报不可用'
  }
  if (!isNativePlatform && !('speechSynthesis' in window)) {
    return '当前浏览器不支持'
  }
  if (isPaused.value) {
    return '已暂停'
  }
  if (isSpeaking.value) {
    return '正在播报'
  }
  return buildSpeechText() ? '可播报查询报告' : '暂无可播报内容'
})

const previewText = computed(() => {
  const text = buildSpeechText()
  if (!text) {
    return '查询完成后，可以直接播报查询报告。'
  }
  return text.length > 120 ? `${text.slice(0, 120)}...` : text
})

const pickChineseVoice = () => {
  const voices = window.speechSynthesis.getVoices()
  return (
    voices.find((voice) => voice.lang.toLowerCase().startsWith('zh-cn')) ||
    voices.find((voice) => voice.lang.toLowerCase().startsWith('zh')) ||
    null
  )
}

const attachNativeListener = async () => {
  if (!isNativePlatform || nativeListener.value) {
    return
  }

  nativeListener.value = await NativeTtsPlayer.addListener('playbackState', (data) => {
    if (data.state === 'playing') {
      isSpeaking.value = true
      isPaused.value = false
      return
    }
    if (data.state === 'paused') {
      isSpeaking.value = false
      isPaused.value = true
      return
    }
    if (data.state === 'completed' || data.state === 'stopped') {
      isSpeaking.value = false
      isPaused.value = false
      return
    }
    if (data.state === 'error') {
      isSpeaking.value = false
      isPaused.value = false
      ElMessage.warning(data.message || '原生语音播报失败')
    }
  })
}

const checkNativeAvailability = async () => {
  if (!isNativePlatform) {
    return
  }
  try {
    const result = await NativeTtsPlayer.available()
    nativeTtsAvailable.value = result.available
  } catch {
    nativeTtsAvailable.value = false
  }
}

const startSpeaking = async () => {
  if (!isNativePlatform && !('speechSynthesis' in window)) {
    ElMessage.warning('当前浏览器不支持语音播报')
    return
  }

  const text = buildSpeechText()
  if (!text) {
    ElMessage.warning('暂无可播报的查询报告')
    return
  }

  if (isNativePlatform) {
    try {
      await attachNativeListener()
      await NativeTtsPlayer.speak({
        text,
        lang: 'zh-CN',
        rate: 0.95,
        pitch: 1.0,
        volume: 1.0,
        preferFemale: true,
      })
      isSpeaking.value = true
      isPaused.value = false
    } catch (error: any) {
      ElMessage.warning(error?.message || '原生语音播报启动失败')
    }
    return
  }

  window.speechSynthesis.cancel()
  ignoreBrowserCancelError.value = false

  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'zh-CN'
  utterance.rate = 0.95
  utterance.pitch = 1

  const voice = pickChineseVoice()
  if (voice) {
    utterance.voice = voice
  }

  utterance.onstart = () => {
    browserUtterance.value = utterance
    isSpeaking.value = true
    isPaused.value = false
  }

  utterance.onend = () => {
    if (browserUtterance.value === utterance) {
      browserUtterance.value = null
    }
    isSpeaking.value = false
    isPaused.value = false
    ignoreBrowserCancelError.value = false
  }

  utterance.onerror = (event) => {
    if (
      ignoreBrowserCancelError.value ||
      event.error === 'canceled' ||
      event.error === 'interrupted'
    ) {
      if (browserUtterance.value === utterance) {
        browserUtterance.value = null
      }
      isSpeaking.value = false
      isPaused.value = false
      ignoreBrowserCancelError.value = false
      return
    }
    if (browserUtterance.value === utterance) {
      browserUtterance.value = null
    }
    isSpeaking.value = false
    isPaused.value = false
    ElMessage.warning('语音播报失败，请检查浏览器语音设置')
  }

  window.speechSynthesis.speak(utterance)
}

const pauseSpeaking = async () => {
  if (isNativePlatform) {
    try {
      await NativeTtsPlayer.pause()
      isSpeaking.value = false
      isPaused.value = true
    } catch (error: any) {
      ElMessage.warning(error?.message || '暂停播报失败')
    }
    return
  }

  if (!('speechSynthesis' in window) || !window.speechSynthesis.speaking) {
    return
  }
  window.speechSynthesis.pause()
  isPaused.value = true
}

const resumeSpeaking = async () => {
  if (isNativePlatform) {
    try {
      await NativeTtsPlayer.resume()
      isPaused.value = false
      isSpeaking.value = true
    } catch (error: any) {
      ElMessage.warning(error?.message || '继续播报失败')
    }
    return
  }

  if (!('speechSynthesis' in window)) {
    return
  }
  window.speechSynthesis.resume()
  isPaused.value = false
  isSpeaking.value = true
}

const stopSpeaking = async () => {
  if (isNativePlatform) {
    try {
      await NativeTtsPlayer.stop()
    } catch {
      // 忽略停止时异常，优先保证 UI 状态回收。
    }
    isSpeaking.value = false
    isPaused.value = false
    return
  }

  if (!('speechSynthesis' in window)) {
    return
  }
  ignoreBrowserCancelError.value = true
  window.speechSynthesis.cancel()
  browserUtterance.value = null
  isSpeaking.value = false
  isPaused.value = false
}

watch(
  () => props.summary,
  () => {
    void stopSpeaking()
  }
)

onMounted(() => {
  void checkNativeAvailability()
  void attachNativeListener()
})

onBeforeUnmount(() => {
  void stopSpeaking()
  if (nativeListener.value) {
    void nativeListener.value.remove()
    nativeListener.value = null
  }
})
</script>

<style scoped>
.speech-body {
  display: grid;
  gap: 14px;
}

.speech-body.compact {
  gap: 10px;
}

.speech-preview-wrap {
  padding: 14px 16px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: #f8fbff;
}

.speech-preview {
  min-height: 48px;
  margin: 0;
  color: #344255;
  font-size: 14px;
  line-height: 1.7;
}

.speech-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.status-text {
  margin-right: 4px;
  color: #5f6f86;
  font-size: 13px;
  white-space: nowrap;
}

.speech-actions :deep(.el-button) {
  margin-left: 0;
}

@media (max-width: 640px) {
  .speech-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }

  .status-text {
    grid-column: 1 / -1;
  }
}
</style>
