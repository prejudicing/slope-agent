import { Capacitor } from '@capacitor/core'
import axios from 'axios'
import type { QueryResponse, QueryStreamEvent } from '../types/query'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

function buildApiUrl(path: string): string {
  if (Capacitor.isNativePlatform() && !API_BASE_URL) {
    throw new Error('安卓 App 需要配置 VITE_API_BASE_URL，例如 http://10.61.48.10:8000')
  }
  return API_BASE_URL ? `${API_BASE_URL}${path}` : path
}

// 非流式接口保留给调试；当前页面主要使用 streamQuery。
export async function postQuery(question: string): Promise<QueryResponse> {
  const res = await axios.post(buildApiUrl('/api/query'), {
    question,
  })
  return res.data
}

export async function streamQuery(
  question: string,
  onEvent: (event: QueryStreamEvent) => void
) {
  const requestUrl = buildApiUrl('/api/query/stream')
  // 使用 fetch 读取 text/event-stream，便于边查询边展示 Agent 进度。
  let res: Response
  try {
    res = await fetch(requestUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ question }),
    })
  } catch (error) {
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

    buffer += decoder.decode(value, { stream: true })
    // SSE 事件用空行分隔；最后一个不完整片段留到下一次 read 再解析。
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''

    for (const chunk of chunks) {
      // 当前后端只发送 data 行，解析后交给页面按事件类型更新不同组件。
      const line = chunk
        .split('\n')
        .find((item) => item.startsWith('data: '))
      if (!line) {
        continue
      }
      onEvent(JSON.parse(line.slice(6)) as QueryStreamEvent)
    }
  }
}
