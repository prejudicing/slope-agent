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
