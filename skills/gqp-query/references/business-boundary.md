# Business Boundary

## In Scope

- 高切坡基础信息
- 群测群防
- 专业监测
- 巡查记录
- 预警专报
- 复核处理
- 报告附件
- 空间数据关联
- 异常状态、裂缝、落石、挡墙、排水等业务问题

## Out of Scope

- 账号、权限、密码、角色、菜单、系统管理
- 通用编程、写作、翻译、天气、股票、新闻等非高切坡问题
- 非只读数据库操作

## SQL Rules

1. Only allow `SELECT` or `WITH`.
2. Block `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `MERGE`, `CALL`, `EXEC`.
3. Do not use `SELECT *`.
4. Keep column order stable.
5. Use deterministic ordering for detail queries.
6. Do not hard-code `LIMIT 20` by default.
7. Only add row limits when the user explicitly asks for top-N / first-N / recent-N / paged viewing.

## Summary Rules

1. The result table is the fact source.
2. The summary must not invent facts not present in the returned rows.
3. For analysis questions, summarize patterns and distributions, but do not invent causes or handling advice.
