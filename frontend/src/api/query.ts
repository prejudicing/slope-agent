import { Capacitor, CapacitorHttp } from '@capacitor/core'
import axios from 'axios'
import type { AsrResponse, QueryResponse, QueryStreamEvent } from '../types/query'

const DEFAULT_NATIVE_API_BASE_URL = 'http://192.168.31.75:8002'
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

function makeQueryString(params: Record<string, unknown> = {}): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') {
      return
    }
    search.set(key, String(value))
  })

  const text = search.toString()
  return text ? `?${text}` : ''
}

async function nativeGet<T>(path: string, params: Record<string, unknown> = {}): Promise<T> {
  const nativeResponse = await CapacitorHttp.get({
    url: `${buildBackendUrl(path)}${makeQueryString(params)}`,
    responseType: 'json',
  })

  if (nativeResponse.status < 200 || nativeResponse.status >= 300) {
    throw new Error(`璇锋眰澶辫触锛?{nativeResponse.status}`)
  }

  return nativeResponse.data as T
}

async function nativePost<T>(path: string, data: Record<string, unknown>): Promise<T> {
  const nativeResponse = await CapacitorHttp.post({
    url: buildBackendUrl(path),
    headers: {
      'Content-Type': 'application/json',
    },
    data,
    responseType: 'json',
  })

  if (nativeResponse.status < 200 || nativeResponse.status >= 300) {
    throw new Error(`璇锋眰澶辫触锛?{nativeResponse.status}`)
  }

  return nativeResponse.data as T
}

export function buildBackendUrl(path: string): string {
  if (API_BASE_URL) {
    return `${API_BASE_URL}${path}`
  }

  if (Capacitor.isNativePlatform()) {
    return `${DEFAULT_NATIVE_API_BASE_URL}${path}`
  }

  if (typeof window !== 'undefined' && window.location.port === '8000') {
    return `${window.location.protocol}//${window.location.hostname}:8002${path}`
  }

  return path
}

export function buildApiUrl(path: string): string {
  return buildBackendUrl(path)
}

export function buildPhotoCacheUrl(path: string, size = 'thumb'): string {
  const raw = String(path || '').trim()
  if (!raw) {
    return ''
  }
  const params = new URLSearchParams({
    path: raw,
    size,
  })
  return buildBackendUrl(`/api/photo-cache?${params.toString()}`)
}

export type QueryHistoryItem = {
  question: string
  summary?: string
  total_rows?: number
}

export async function postQuery(question: string, history: QueryHistoryItem[] = []): Promise<QueryResponse> {
  if (Capacitor.isNativePlatform()) {
    return nativePost<QueryResponse>('/api/query', { question, history })
  }

  const res = await axios.post(buildBackendUrl('/api/query'), {
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
    return nativePost<AsrResponse>('/api/asr', payload)
  }

  const res = await axios.post(buildBackendUrl('/api/asr'), payload)
  return res.data
}

export async function fetchRecentLargeDisplacement() {
  if (Capacitor.isNativePlatform()) {
    return nativeGet('/api/displacement/recent-large', { _t: Date.now() })
  }

  const res = await axios.get(buildBackendUrl('/api/displacement/recent-large'), {
    params: { _t: Date.now() },
  })
  return res.data
}

export async function fetchQmqfAbnormalDashboard() {
  if (Capacitor.isNativePlatform()) {
    return nativeGet('/api/qmqf/abnormal-dashboard', { _t: Date.now() })
  }

  const res = await axios.get(buildBackendUrl('/api/qmqf/abnormal-dashboard'), {
    params: { _t: Date.now() },
  })
  return res.data
}

export async function fetchReportStabilityAssets(params: Record<string, unknown> = {}) {
  const requestParams = { limit: 12, only_with_photos: true, _t: Date.now(), ...params }

  if (Capacitor.isNativePlatform()) {
    return nativeGet('/api/report/stability-assets', requestParams)
  }

  const res = await axios.get(buildBackendUrl('/api/report/stability-assets'), {
    params: requestParams,
  })
  return res.data
}

export async function streamQuery(
  question: string,
  onEvent: (event: QueryStreamEvent) => void,
  history: QueryHistoryItem[] = []
) {
  if (Capacitor.isNativePlatform()) {
    onEvent({
      type: 'progress',
      message: '安卓 App 正在连接业务数据服务',
      detail: '正在通过手机原生网络通道请求后端。',
    })

    const data = await nativePost<QueryResponse>('/api/query', { question, history })

    if (data.sql) {
      onEvent({ type: 'sql', sql: data.sql })
    }

    if (data.summary || data.result) {
      onEvent({
        type: 'summary',
        summary: data.summary || data.result,
        message: '已生成业务回答',
      })
    }

    onEvent({
      type: 'final',
      data,
    })
    return
  }

  const requestUrl = buildBackendUrl('/api/query/stream')
  let res: Response
  try {
    res = await fetch(requestUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ question, history }),
    })
  } catch (error) {
    throw new Error(`请求失败，无法访问 ${requestUrl}。请检查后端地址、服务状态或跨域配置。`)
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
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''

    for (const chunk of chunks) {
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
