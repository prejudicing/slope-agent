# Response Schema

Use this unified response structure for query-capable questions:

```json
{
  "status": "success | clarify | rejected | error",
  "query_type": "db_query | result_analysis | template_query | clarify | out_of_scope",
  "question": "用户原始问题",
  "sql": "最终执行的只读 SQL，非查询类可为空字符串",
  "result": "兼容字段，可与 summary 保持一致",
  "summary": "给用户看的中文总结",
  "report": null,
  "suggestion": "澄清或拒答时给用户的下一步建议；正常查询可为 null",
  "columns": [],
  "rows": [],
  "logs": "后端内部日志文本，可选保留",
  "error": null
}
```

## Field Expectations

- `status`
  - `success`: 已完成查询或结果分析
  - `clarify`: 问题条件不足
  - `rejected`: 越界拒答
  - `error`: 执行失败

- `query_type`
  - Must be one of the 5 route types only

- `sql`
  - Must be empty for `clarify` and `out_of_scope`
  - Must be read-only for query paths

- `summary`
  - User-facing
  - Based on real query results only

- `columns` / `rows`
  - The source of truth for the result table

- `logs`
  - Internal/debug-oriented
  - Not required to be shown in a user-facing page
