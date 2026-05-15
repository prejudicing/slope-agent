# Routing Spec

The high-cut-slope query workflow uses 5 mutually exclusive route types:

## `db_query`

- Meaning: ordinary fact query against the real database
- Focus: "what data is there"
- Examples:
  - 最近有哪些高切坡存在异常状态
  - 统计各区县高切坡数量
  - 查询最近30天的预警专报记录

## `result_analysis`

- Meaning: analysis, comparison, trend, or synthesis question that still depends on real query results
- Focus: "how to interpret the result"
- Examples:
  - 帮我分析最近异常高切坡的分布情况
  - 对比一下各区县高切坡异常数量
  - 总结一下近一个月哪些区县高切坡异常比较多

## `template_query`

- Meaning: high-risk high-frequency business question that must use a stable template
- Focus: "do not let the model drift"
- Example:
  - 我想知道哪些高切坡处于异常状态，并告诉我属于哪一种异常类型

## `clarify`

- Meaning: too short, too vague, or missing essential business scope
- Focus: ask the user to add region, time, object, or anomaly details
- Examples:
  - 查一下
  - 看看异常
  - 帮我分析一下

## `out_of_scope`

- Meaning: outside high-cut-slope business scope, or sensitive system-management questions
- Focus: refuse and redirect to business scope
- Examples:
  - 查询系统账号和密码
  - 查看权限配置
  - 帮我写一段 Python 代码

## Implementation Principles

1. `query_type` must stay within these 5 values.
2. Cache hit, template hit, or analysis prompt selection are execution details, not new route types.
3. The same user question should keep a stable `query_type` across executions.
