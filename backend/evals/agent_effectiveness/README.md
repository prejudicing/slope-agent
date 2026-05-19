# Agent 效果测试

这个目录用于集中管理高切坡智能查询 Agent 的正式评测材料，避免测试题、结果文件和分析报告散落在 `docs/notes`、`backend/runtime` 等位置。

## 目录结构

- `docs/`
  - 测试方案、路由规范、题集说明等文档。
- `datasets/`
  - 测试题集，按场景和规模组织。
- `results/`
  - 每次批量执行后的结构化 JSON 结果，文件名带时间戳。
- `reports/`
  - 每次批量执行后的 Markdown 分析报告，文件名带时间戳。

## 当前正式题集

- `datasets/agent_eval_5routes_20each.json`

## 配套文档

- `docs/Agent效果测试方案.md`
- `docs/agent_eval_5routes_20each.md`
- `docs/查询结果与报告评估题集.md`
- `docs/最小路由测试样例.md`
- `docs/查询路由分类规范.md`

这份题集包含 5 类路由，每类 20 题，共 100 题：

1. `db_query`
2. `template_query`
3. `result_analysis`
4. `clarify`
5. `out_of_scope`

## 推荐执行方式

在可访问达梦数据库的环境中运行：

### 1. 运行完整正式评测（100 题）

```bash
conda run -n dm python backend/evals/agent_effectiveness/scripts/run_agent_effectiveness_eval.py
```

输出会自动写入：

- `backend/evals/agent_effectiveness/results/agent_effectiveness_results_YYYYMMDD_HHMMSS.json`
- `backend/evals/agent_effectiveness/reports/agent_effectiveness_report_YYYYMMDD_HHMMSS.md`

结果 JSON 会记录：

- 每题开始时间
- 每题结束时间
- 每题耗时（秒）
- 总耗时（秒）
- 平均每题耗时（秒）

### 2. 只跑某一类路由

例如只跑 `db_query`：

```bash
conda run -n dm python backend/evals/agent_effectiveness/scripts/run_agent_effectiveness_eval.py --route db_query
```

例如只跑 `template_query` 和 `result_analysis`：

```bash
conda run -n dm python backend/evals/agent_effectiveness/scripts/run_agent_effectiveness_eval.py --route template_query --route result_analysis
```

### 3. 先做少量烟测

例如只跑前 5 题：

```bash
conda run -n dm python backend/evals/agent_effectiveness/scripts/run_agent_effectiveness_eval.py --limit 5
```

### 4. 控制单题超时

例如把单题超时设为 60 秒：

```bash
conda run -n dm python backend/evals/agent_effectiveness/scripts/run_agent_effectiveness_eval.py --per-case-timeout 60
```

## 轻量批量脚本

如果只想快速跑一组常用题，可以用：

```bash
conda run -n dm python backend/evals/agent_effectiveness/scripts/run_query_eval.py
```

只跑前 5 题：

```bash
conda run -n dm python backend/evals/agent_effectiveness/scripts/run_query_eval.py --limit 5
```

只跑某一道题：

```bash
conda run -n dm python backend/evals/agent_effectiveness/scripts/run_query_eval.py --question "查询渝北区高切坡基本信息"
```

输出同样会进入：

- `backend/evals/agent_effectiveness/results/`

## 说明

从现在起，正式评测请统一使用这个目录中的题集、脚本、结果和报告。
