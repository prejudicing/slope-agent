import axios from 'axios'
import type { QueryResponse, QueryStreamEvent } from '../types/query'

export async function postQuery(question: string): Promise<QueryResponse> {
  const res = await axios.post('/api/query', {
    question,
  })
  return res.data
}

export async function streamQuery(
  question: string,
  onEvent: (event: QueryStreamEvent) => void
) {
  const res = await fetch('/api/query/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ question }),
  })

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
