---
name: gqp-query
description: Route and answer high-cut-slope database questions with a fixed 5-type classification, a standard query workflow, and a stable response schema. Use when the user is asking to query, count, analyze, compare, summarize, or explain high-cut-slope business data such as basic records, monitoring, patrols, warnings, reviews, or abnormal conditions.
---

# GQP Query

Use this skill for high-cut-slope business queries that should go through the database-backed query workflow.

## Workflow

1. Classify the question into exactly one of the 5 route types in [references/routing-spec.md](references/routing-spec.md):
   - `db_query`
   - `result_analysis`
   - `template_query`
   - `clarify`
   - `out_of_scope`

2. If the type is `clarify` or `out_of_scope`:
   - Do not enter the SQL query chain.
   - Return the standard response shape from [references/response-schema.md](references/response-schema.md).
   - Provide a short, user-facing summary and suggestion.

3. If the type is `template_query`:
   - Prefer the stable template route.
   - Do not let the model freely change table/field selection.
   - Query first, then summarize the real result table.

4. If the type is `db_query`:
   - Select candidate tables from real schema knowledge.
   - Generate read-only SQL.
   - Query the database.
   - Return structured table data and a factual summary.

5. If the type is `result_analysis`:
   - Query the database first.
   - Then generate an analysis-style summary from the real result table.
   - The analysis must not invent causes, actions, or facts that are not present in the query result.

## Required Rules

- Only handle high-cut-slope business questions.
- Only generate read-only SQL (`SELECT` / `WITH`).
- Never query account, permission, password, or system-management data.
- Do not default to hard-coded `LIMIT 20`.
- Only add row limits when the user explicitly asks for top-N, first-N, recent-N, or paged viewing.
- The result table is the source of truth; the summary must be based on the real query result.
- `query_type` is a business classification, not an execution detail. Do not return ad hoc values such as `cached_query` or `deterministic`.

## Standard Output

Always follow the unified response contract in [references/response-schema.md](references/response-schema.md).

## References

- Routing categories and meanings: [references/routing-spec.md](references/routing-spec.md)
- Response contract: [references/response-schema.md](references/response-schema.md)
- Minimal manual test set: [references/query-examples.md](references/query-examples.md)
- Business boundary and SQL rules: [references/business-boundary.md](references/business-boundary.md)
