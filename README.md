# 高切坡系统智能查询 Agent

一个面向高切坡业务的自然语言查询系统。  
用户可以直接输入中文问题，系统结合真实数据库 schema、业务解释、问题路由和 SQL Agent，自动查询达梦数据库，并返回：

- 生成 SQL
- 查询结果表格
- 查询报告
- Agent 查询过程 / 日志
- 查询结果语音播报
- 分享与 PDF 导出

## 当前能力

- 支持高切坡基础信息、群测群防、专业监测、预警专报、巡查记录、空间资料等业务查询
- 支持 5 类问题路由：
  - `db_query`
  - `template_query`
  - `result_analysis`
  - `clarify`
  - `out_of_scope`
- 支持高频业务问题的稳定模板 SQL
- 支持同义词和口语归一化，例如“渝北地区”自动归一为“渝北区”
- 支持 SQL 口径缓存，减少重复提问时的结果漂移
- 支持大结果集“总条数 + 样本展示”模式，避免前端直接承载全量结果
- 支持双阶段模型：
  - 查询阶段模型：优先保证 SQL 查询稳定
  - 报告阶段模型：专门生成查询报告
- 支持中文语音输入
- 支持结果播报、分享和 PDF 导出
- 支持基于 Vue 前端封装 Android App
- 支持正式 Agent 评测目录、批量评测脚本和时间戳结果导出

## 项目结构

```text
lm-dm8/
├─ backend/
│  ├─ app/
│  │  ├─ agent.py                 # Agent 主流程、流式事件、查询结果回查、报告生成
│  │  ├─ api.py                   # FastAPI 查询接口
│  │  ├─ business_queries.py      # 高频问题确定性 SQL 模板
│  │  ├─ config.py                # 环境变量配置（支持查询/报告双模型）
│  │  ├─ db.py                    # 达梦数据库连接
│  │  ├─ domain.py                # Agent Prompt 和业务边界
│  │  ├─ main.py                  # FastAPI 应用入口
│  │  ├─ query_cache.py           # 问题 -> SQL 稳定缓存
│  │  ├─ query_router.py          # 五类问题路由
│  │  ├─ question_normalizer.py   # 口语/区县同义词归一化
│  │  └─ schema_knowledge.py      # schema 知识召回和候选表选择
│  ├─ evals/
│  │  └─ agent_effectiveness/     # 正式评测目录（题集、脚本、结果、报告）
│  ├─ runtime/
│  │  └─ query_sql_cache.json     # 运行时 SQL 缓存
│  ├─ schema_exports/             # 真实库 schema 导出和解释结果
│  ├─ scripts/                    # schema 导出、解释、画像、枚举校验脚本
│  └─ requirements.txt
├─ frontend/
│  ├─ android/                    # Capacitor 生成的 Android 原生工程
│  ├─ src/
│  │  ├─ api/                     # 前端请求
│  │  ├─ components/              # Vue 组件（查询输入、查询报告、结果表格等）
│  │  ├─ types/                   # TS 类型
│  │  ├─ App.vue
│  │  └─ main.ts
│  ├─ scripts/
│  │  └─ create-dev-cert.mjs      # 本地 HTTPS 证书生成
│  ├─ package.json
│  └─ vite.config.ts
├─ docs/
│  └─ notes/                      # 其他开发说明与人工校验文档
└─ 数据库设计文档.docx            # 当前数据库设计文档参考
```

## 技术栈

### 后端

- FastAPI
- Uvicorn
- LangChain / langchain-community / langchain-openai
- SQLAlchemy
- dmPython / dmSQLAlchemy

### 前端

- Vue 3
- TypeScript
- Vite
- Capacitor
- Element Plus
- Web Speech API（中文语音输入）
- SpeechSynthesis（结果播报）
- html2canvas / jsPDF（导出 PDF）

## 运行前准备

### 1. Python 环境

建议 Python 3.10+。

安装后端依赖：

```bash
cd /home/lzb/projects/lm-dm8/backend
pip install -r requirements.txt
```

### 2. Node 环境

建议 Node.js 18+。

安装前端依赖：

```bash
cd /home/lzb/projects/lm-dm8/frontend
npm install
```

### 3. 后端环境变量

在 `backend/.env` 中配置。

#### 达梦数据库

```env
DM_USER=你的达梦用户名
DM_PASSWORD=你的达梦密码
DM_HOST=你的达梦主机
DM_PORT=5236
```

#### 通用默认模型

如果不单独拆查询/报告模型，会回退到这一组：

```env
OPENAI_API_KEY=你的默认模型接口Key
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=你的模型接口Base URL
```

#### 查询阶段模型

查询阶段更强调 SQL 生成稳定性，通常建议关闭 thinking：

```env
QUERY_PROVIDER=openai
QUERY_API_KEY=你的查询模型Key
QUERY_MODEL=gpt-4o-mini
QUERY_BASE_URL=你的查询模型Base URL
QUERY_THINKING_ENABLED=false
```

#### 报告阶段模型

报告阶段可以和查询阶段使用不同模型：

```env
REPORT_PROVIDER=deepseek
REPORT_API_KEY=你的报告模型Key
REPORT_MODEL=deepseek-v4-flash
REPORT_BASE_URL=https://api.deepseek.com
REPORT_THINKING_ENABLED=true
REPORT_REASONING_EFFORT=high
```

#### 语音转写

```env
ASR_MODEL=small
ASR_DEVICE=cpu
ASR_COMPUTE_TYPE=int8
```

#### 可选：调试用业务表覆盖

```env
HCS_INCLUDE_TABLES=tb_hcs_monitoring,geo_gqp_jbxx
```

如果不配置 `HCS_INCLUDE_TABLES`，系统会根据问题和 schema 知识自动选择候选表。

## 启动方式

### 方式一：本地开发推荐

启动后端：

```bash
cd /home/lzb/projects/lm-dm8/backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

启动前端 HTTPS 开发服务：

```bash
cd /home/lzb/projects/lm-dm8/frontend
npm run dev:https
```

访问地址：

```text
https://localhost:5173/
```

说明：

- `dev:https` 首次运行会自动生成本地自签名证书
- 浏览器第一次访问时会提示证书不安全，开发环境下手动继续访问即可
- 前端会把 `/api` 代理到 `http://127.0.0.1:8000`

### 方式二：仅前端 HTTP 开发

如果你暂时不需要语音输入，也可以使用普通 HTTP：

```bash
cd /home/lzb/projects/lm-dm8/frontend
npm run dev
```

访问：

```text
http://localhost:5173/
```

注意：中文语音输入通常要求 `HTTPS` 或 `localhost` 安全上下文。

### 方式三：Android App

先准备 Android App 请求的后端地址：

```bash
cd /home/lzb/projects/lm-dm8/frontend
cp .env.example .env.local
```

然后把 `.env.local` 里的地址改成你的后端地址，例如：

```env
VITE_API_BASE_URL=http://10.61.48.10:8000
```

构建并同步到 Android 工程：

```bash
cd /home/lzb/projects/lm-dm8/frontend
npm run android:sync
```

用 Android Studio 打开：

```bash
cd /home/lzb/projects/lm-dm8/frontend
npm run android:open
```

说明：

- 当前安卓工程默认允许访问 HTTP 后端，便于局域网联调
- 如果更换后端地址，需要重新执行 `npm run android:sync`

## 前端常用命令

```bash
cd /home/lzb/projects/lm-dm8/frontend
```

生成 HTTPS 开发证书：

```bash
npm run cert
```

启动 HTTPS 开发服务：

```bash
npm run dev:https
```

构建前端：

```bash
npm run build
```

同步 Android 工程：

```bash
npm run android:sync
```

打开 Android Studio：

```bash
npm run android:open
```

## 后端常用命令

```bash
cd /home/lzb/projects/lm-dm8/backend
```

开发启动：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 关键接口

健康检查：

```text
GET /api/health
```

普通查询：

```text
POST /api/query
```

流式查询：

```text
POST /api/query/stream
```

当前前端页面主要使用流式查询接口。

## schema 知识文件

系统当前以真实数据库导出的 schema 作为主要依据，设计文档仅作为参考。

核心文件位于：

```text
backend/schema_exports/database_schema.json
backend/schema_exports/document_schema.json
backend/schema_exports/schema_comparison.json
backend/schema_exports/database_schema_explained.json
backend/schema_exports/schema_chunks.jsonl
backend/schema_exports/table_profile.json
backend/schema_exports/core_table_candidates.json
backend/schema_exports/business_starter_pack.json
backend/schema_exports/enum_fields_01_review.csv
```

用途概览：

- `database_schema.json`：真实数据库表结构
- `document_schema.json`：Word 文档提取结果
- `schema_comparison.json`：设计文档与真实数据库差异
- `database_schema_explained.json`：带中文业务解释的 schema
- `schema_chunks.jsonl`：schema 检索块
- `table_profile.json`：真实表画像
- `core_table_candidates.json`：核心表候选
- `business_starter_pack.json`：Agent 初始业务知识包
- `enum_fields_01_review.csv`：`0/1` 枚举字段人工校验清单

## schema 脚本

导出真实数据库 schema 并与 Word 文档对比：

```bash
cd /home/lzb/projects/lm-dm8/backend
python scripts/export_and_compare_schema.py
```

生成带业务解释的 schema：

```bash
python scripts/generate_explained_schema.py
```

生成表画像、核心表候选和 starter pack：

```bash
python scripts/profile_business_schema.py
```

导出 `0/1` 枚举字段人工校验清单：

```bash
python scripts/export_enum_review.py
```

## 当前系统行为说明

### 1. 查询结果和查询报告分离

- 查询结果表格来自真实 SQL 查询返回的 `columns` 和 `rows`
- 查询报告来自报告阶段模型，基于真实结果表生成

### 2. 五类问题路由

系统会先进行问题路由，再决定执行路径：

- `db_query`：普通数据库查询
- `template_query`：命中稳定业务模板
- `result_analysis`：先查库，再生成分析型报告
- `clarify`：问题过于模糊，要求补充条件
- `out_of_scope`：越界或敏感问题，直接拒答

### 3. 稳定 SQL 缓存

系统会把“相同自然语言问题 -> 已验证 SQL”保存到：

```text
backend/runtime/query_sql_cache.json
```

这样重复提问时，可以复用稳定查询口径，减少结果漂移。

如需清空缓存：

```bash
rm /home/lzb/projects/lm-dm8/backend/runtime/query_sql_cache.json
```

### 4. 高频稳定业务模板

对部分关键问题，系统不会交给 LLM 自由发挥，而是走确定性 SQL 模板。例如：

- 异常状态 + 异常类型
- 各区县异常高切坡数量对比

### 5. 大结果集展示

当前系统对大结果集采用：

- 后端单独统计 `total_rows`
- 前端只展示前若干条样本

这样可以避免一次把几十万行结果直接压给前端。

## Agent 效果测试

正式评测材料已经集中到：

[backend/evals/agent_effectiveness/README.md](/home/lzb/projects/lm-dm8/backend/evals/agent_effectiveness/README.md)

常用命令：

完整 100 题正式评测：

```bash
conda run -n dm python backend/evals/agent_effectiveness/scripts/run_agent_effectiveness_eval.py
```

只跑前 5 题：

```bash
conda run -n dm python backend/evals/agent_effectiveness/scripts/run_agent_effectiveness_eval.py --limit 5
```

轻量批量测试：

```bash
conda run -n dm python backend/evals/agent_effectiveness/scripts/run_query_eval.py
```

题集人工阅读版：

[agent_eval_5routes_20each.md](/home/lzb/projects/lm-dm8/backend/evals/agent_effectiveness/docs/agent_eval_5routes_20each.md)

## 语音功能说明

### 中文语音输入

- 入口：查询输入框右侧“中文语音输入”
- 浏览器要求：通常需要 `HTTPS` 或 `localhost`
- 推荐浏览器：Chrome / Edge
- 手机访问时需要连接同一局域网
- 安卓 App 场景下，前端请求地址必须通过 `VITE_API_BASE_URL` 指向真实后端，不能依赖相对路径 `/api`

### 查询结果播报

- 支持开始播报 / 暂停 / 继续 / 停止
- 播报内容包括查询报告和前几条表格结果
- 使用浏览器内置 `speechSynthesis`

## 常见问题

### 1. 为什么手机上语音输入没反应？

优先检查：

- 是否使用了 HTTPS 地址
- 是否点击了继续访问自签名证书页面
- 是否已授权麦克风
- 是否和开发机在同一局域网

### 2. 为什么同一个问题有时结果不一样？

当前系统已经增加：

- 问题归一化
- 稳定 SQL 缓存
- 高频问题稳定模板
- 五类问题路由

如果需要重新生成 SQL，可以删除：

```bash
rm /home/lzb/projects/lm-dm8/backend/runtime/query_sql_cache.json
```

### 3. 为什么设计文档中的表在数据库里找不到？

因为当前项目已经验证过：数据库设计文档和真实达梦数据库并不完全一致。  
系统现在以真实数据库导出的 schema 为准，设计文档仅作辅助参考。

### 4. 为什么 `.gitignore` 写了 `.vscode/`、`.codex/`，仓库里还有这些文件？

因为 `.gitignore` 只对**尚未被 Git 跟踪的文件**生效。  
如果文件早就被提交过，需要先把它从 Git 索引里移除，后续 ignore 规则才会真正接管。
