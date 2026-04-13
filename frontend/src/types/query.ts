export interface QueryResponse {
  question: string
  sql: string
  result: string
  summary: string
  columns: string[]
  rows: Record<string, string>[]
  logs: string
  error: string | null
}

export interface ThinkingStep {
  id: number
  time: string
  title: string
  detail?: string
  status: 'running' | 'done' | 'error'
}

export type QueryStreamEvent =
  | {
      type: 'progress'
      message: string
      detail?: string
    }
  | {
      type: 'sql'
      sql: string
    }
  | {
      type: 'summary'
      summary: string
      message?: string
    }
  | {
      type: 'final'
      data: QueryResponse
    }
  | {
      type: 'error'
      message: string
    }
