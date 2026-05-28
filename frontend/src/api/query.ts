import { Capacitor, CapacitorHttp } from '@capacitor/core'
import axios from 'axios'
import type {
  AsrResponse,
  ConversationHistoryTurn,
  QueryResponse,
  QueryStreamEvent,
} from '../types/query'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

export function buildApiUrl(path: string): string {
  if (Capacitor.isNativePlatform() && !API_BASE_URL) {
    throw new Error('安卓 App 需要配置 VITE_API_BASE_URL，例如 http://10.61.48.10:8000')
  }
  return API_BASE_URL ? `${API_BASE_URL}${path}` : path
}

// 非流式接口保留给调试；当前页面主要使用 streamQuery。
export async function postQuery(
  question: string,
  history: ConversationHistoryTurn[] = []
): Promise<QueryResponse> {
  const res = await axios.post(buildApiUrl('/api/query'), {
    question,
    history,
  })
  return res.data
}

export async function transcribeAudio(
  audioBase64: string,
  mimeType: string,
  filename = 'query_audio.m4a'
): Promise<AsrResponse> {
  const payload = {
    audio_base64: audioBase64,
    mime_type: mimeType,
    filename,
  }

  if (Capacitor.isNativePlatform()) {
    const nativeResponse = await CapacitorHttp.post({
      url: buildApiUrl('/api/asr'),
      headers: {
        'Content-Type': 'application/json',
      },
      data: payload,
      responseType: 'json',
    })

    if (nativeResponse.status < 200 || nativeResponse.status >= 300) {
      throw new Error(`语音转写请求失败：${nativeResponse.status}`)
    }

    return nativeResponse.data as AsrResponse
  }

  const res = await axios.post(buildApiUrl('/api/asr'), payload)
  return res.data
}

export async function streamQuery(
  question: string,
  onEvent: (event: QueryStreamEvent) => void,
  history: ConversationHistoryTurn[] = [],
  options: {
    signal?: AbortSignal
    isCancelled?: () => boolean
  } = {}
) {
  const dispatchSseChunk = (chunk: string) => {
    if (options.isCancelled?.()) {
      return
    }
    const line = chunk
      .split('\n')
      .find((item) => item.startsWith('data: '))
    if (!line) {
      return
    }
    onEvent(JSON.parse(line.slice(6)) as QueryStreamEvent)
  }

  if (Capacitor.isNativePlatform()) {
    onEvent({
      type: 'progress',
      message: '安卓 App 正在通过原生网络通道请求后端',
      detail: '原生 HTTP 会绕过 WebView 的跨域限制，结果返回后再展示到页面。',
    })

    const nativeResponse = await CapacitorHttp.post({
      url: buildApiUrl('/api/query'),
      headers: {
        'Content-Type': 'application/json',
      },
      data: {
        question,
        history,
      },
      responseType: 'json',
    })

    if (nativeResponse.status < 200 || nativeResponse.status >= 300) {
      throw new Error(`请求失败：${nativeResponse.status}`)
    }

    if (options.isCancelled?.()) {
      return
    }

    const data = nativeResponse.data as QueryResponse

    if (data.sql) {
      onEvent({ type: 'sql', sql: data.sql })
    }

    if (data.summary || data.result) {
      onEvent({
        type: 'summary',
        summary: data.summary || data.result,
        message: '已生成查询报告',
      })
    }

    onEvent({
      type: 'final',
      data,
    })
    return
  }

  const requestUrl = buildApiUrl('/api/query/stream')
  // 使用 fetch 读取 text/event-stream，便于边查询边展示 Agent 进度。
  let res: Response
  try {
    res = await fetch(requestUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      signal: options.signal,
      body: JSON.stringify({ question, history }),
    })
  } catch (error) {
    if ((error as Error)?.name === 'AbortError') {
      throw error
    }
    throw new Error(
      `请求失败，无法访问 ${requestUrl}。请检查 App 后端地址、服务器连通性或跨域配置。`
    )
  }

  if (!res.ok || !res.body) {
    throw new Error(`请求失败：${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      break
    }

    if (options.isCancelled?.()) {
      return
    }

    buffer += decoder.decode(value, { stream: true })
    // SSE 事件用空行分隔；最后一个不完整片段留到下一次 read 再解析。
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''

    for (const chunk of chunks) {
      // 当前后端只发送 data 行，解析后交给页面按事件类型更新不同组件。
      dispatchSseChunk(chunk)
    }
  }

  if (buffer.trim()) {
    dispatchSseChunk(buffer)
  }
}
