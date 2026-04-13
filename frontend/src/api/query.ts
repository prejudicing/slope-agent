import axios from 'axios'
import type { QueryResponse } from '../types/query'

export async function postQuery(question: string): Promise<QueryResponse> {
  const res = await axios.post('/api/query', {
    question,
  })
  return res.data
}
