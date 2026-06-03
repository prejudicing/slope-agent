export interface QueryAttachment {
  type: 'image' | 'video' | string
  label: string
  path: string
  url: string
  source_url?: string
  hcs_code?: string
  hcs_name?: string
  monitoring_id?: string
  hcs_id?: string
  created_on?: string
  photo_on?: string
}

// 后端最终返回结构。columns/rows 专供查询结果表格使用，summary 当前用于承载查询报告正文。
export interface QueryResponse {
  question: string
  sql: string
  result: string
  summary: string
  columns: string[]
  rows: Record<string, string>[]
  total_rows?: number
  attachments?: QueryAttachment[]
  logs: string
  error: string | null
  suggestion?: string | null
}

export interface AsrResponse {
  text: string
  error: string | null
}

// 思考过程面板中的单个步骤，由 SSE progress/sql/summary 事件转换而来。
export interface ThinkingStep {
  id: number
  time: string
  title: string
  detail?: string
  status: 'running' | 'done' | 'error'
}

// 后端流式事件协议。新增事件类型时需要同步更新 App.vue 的处理逻辑。
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
