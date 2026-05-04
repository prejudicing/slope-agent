<template>
  <el-card shadow="never" class="panel-card speech-card">
    <template #header>
      <div class="panel-header">
        <span>结果播报</span>
        <span class="status-text">{{ statusText }}</span>
      </div>
    </template>

    <div class="speech-body">
      <p class="speech-preview">{{ previewText }}</p>
      <div class="speech-actions">
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
  </el-card>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { PluginListenerHandle } from '@capacitor/core'
import { Capacitor } from '@capacitor/core'
import { ElMessage } from 'element-plus'
import { NativeTtsPlayer } from '../plugins/nativeTtsPlayer'

const props = defineProps<{
  summary: string
  columns: string[]
  rows: Record<string, string>[]
}>()

const isSpeaking = ref(false)
const isPaused = ref(false)
const nativeTtsAvailable = ref(false)
const nativeListener = ref<PluginListenerHandle | null>(null)
const isNativePlatform = Capacitor.isNativePlatform()

const canSpeak = computed(() => {
  if (!buildSpeechText().trim()) {
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
  return '等待播报'
})

const previewText = computed(() => {
  const text = buildSpeechText()
  if (!text) {
    return '查询完成后，可以将查询总结和表格结果朗读出来。'
  }
  return text.length > 120 ? `${text.slice(0, 120)}...` : text
})

const buildSpeechText = () => {
  const parts: string[] = []
  const summary = props.summary.trim()

  if (summary) {
    parts.push(`查询总结：${summary}`)
  }

  if (props.rows.length) {
    parts.push(`查询结果共 ${props.rows.length} 条。`)
    props.rows.slice(0, 5).forEach((row, index) => {
      const rowText = props.columns
        .map((column) => {
          const value = row[column]
          return value ? `${column}：${value}` : ''
        })
        .filter(Boolean)
        .join('，')
      if (rowText) {
        parts.push(`第 ${index + 1} 条，${rowText}。`)
      }
    })
    if (props.rows.length > 5) {
      parts.push('其余结果请查看表格。')
    }
  }

  return parts.join(' ')
}

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
  if (!text.trim()) {
    ElMessage.warning('暂无可播报的查询结果')
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
      })
      isSpeaking.value = true
      isPaused.value = false
    } catch (error: any) {
      ElMessage.warning(error?.message || '原生语音播报启动失败')
    }
    return
  }

  window.speechSynthesis.cancel()

  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'zh-CN'
  utterance.rate = 0.95
  utterance.pitch = 1

  const voice = pickChineseVoice()
  if (voice) {
    utterance.voice = voice
  }

  utterance.onstart = () => {
    isSpeaking.value = true
    isPaused.value = false
  }

  utterance.onend = () => {
    isSpeaking.value = false
    isPaused.value = false
  }

  utterance.onerror = () => {
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
  window.speechSynthesis.cancel()
  isSpeaking.value = false
  isPaused.value = false
}

watch(
  () => [props.summary, props.rows],
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
  color: #5f6f86;
  font-size: 13px;
  font-weight: 400;
}

.speech-body {
  display: grid;
  gap: 14px;
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
  gap: 10px;
}

.speech-actions :deep(.el-button) {
  margin-left: 0;
}

@media (max-width: 640px) {
  .speech-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
}
</style>
