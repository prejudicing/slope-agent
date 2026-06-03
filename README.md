# 高切坡智能查询系统

面向高切坡业务的自然语言查询系统。用户可以直接输入中文问题，后端会结合问题路由、稳定业务模板、数据库 schema、SQL Agent、业务报告生成和现场照片服务，返回可阅读的业务回答、结果表格、图表/照片附件和查询状态。

当前 `feature-v3` 分支已经把后端从单层 `app/` 拆成了更清晰的工程结构，并把主业务数据库抽象为 `DB_PROVIDER`，同时保留现场照片 SQL Server 数据源。

## 核心能力

- 中文自然语言提问，支持高切坡基础信息、群测群防、专业监测、预警专报、巡查记录、月报资产等业务查询。
- 五类问题路由：`db_query`、`template_query`、`result_analysis`、`clarify`、`out_of_scope`。
- 高频问题走确定性 SQL 模板，降低 LLM 自由生成 SQL 带来的漂移。
- 普通问题走 LangChain SQL Agent，并通过真实 schema 知识限定候选表。
- 支持 SQL 结果表格、业务摘要、报告文本、位移图表、现场照片附件。
- 支持大结果集“总条数 + 样本展示”，避免前端一次加载全量数据。
- 支持中文语音输入、语音播报、分享、PDF 导出。
- 支持 Vue 前端封装 Android App。
- 提供工作流图、接口流转图和 Agent 效果评测脚本。

## 项目结构

```text
lm-dm8/
├─ backend/
│  ├─ app/
│  │  ├─ main.py                  # FastAPI 应用入口，挂载 /api 和前端 dist
│  │  ├─ api/                     # HTTP 接口层
│  │  ├─ core/                    # 配置、主库连接、SQL Server 连接
│  │  ├─ services/                # Agent 主流程、ASR、照片服务、照片缓存
│  │  ├─ nlq/                     # 问句路由、归一化、schema 知识、稳定 SQL 模板
│  │  ├─ dashboards/              # 位移、群测群防、监测规模等看板数据
│  │  └─ reports/                 # 月报资产、图表、高切坡对象索引
│  ├─ evals/agent_effectiveness/  # 评测题集、脚本、结果与说明
│  ├─ runtime/                    # 运行时缓存，例如 query_sql_cache.json
│  ├─ schema_exports/             # 数据库 schema、解释结果、表画像
│  ├─ scripts/                    # 数据导入、schema 分析、评测辅助脚本
│  └─ requirements.txt
├─ frontend/
│  ├─ src/
│  │  ├─ api/                     # 前端 API 请求
│  │  ├─ components/              # Vue 业务组件
│  │  ├─ plugins/                 # 移动端 TTS 等插件封装
│  │  ├─ types/                   # TypeScript 类型
│  │  ├─ App.vue
│  │  └─ main.ts
│  ├─ android/                    # Capacitor Android 工程
│  ├─ scripts/                    # 本地 HTTPS 证书、录制等脚本
│  ├─ package.json
│  └─ vite.config.ts
└─ docs/
   └─ diagrams/workflows/         # 后端工作流图和接口流转图
```

## 技术栈

后端：

- FastAPI / Uvicorn
- LangChain / langchain-community / langchain-openai
- SQLAlchemy
- dmPython / dmSQLAlchemy
- python-tds / pyodbc / pymssql
- faster-whisper
- Pillow

前端：

- Vue 3 / TypeScript / Vite
- Element Plus
- ECharts
- Capacitor Android
- Web Speech API / Capacitor 语音插件
- html2canvas / jsPDF

## 数据库说明

`feature-v3` 不再把数据库写死为单一达梦连接，而是通过 `DB_PROVIDER` 决定主业务库。

主业务库：

- `DB_PROVIDER=dm`：达梦数据库，连接方式为 `dm+dmPython`。
- `DB_PROVIDER=sqlserver`：SQL Server，默认连接方式为 `mssql+pytds`，也可以切到 `pyodbc`。

现场照片库：

- 单独使用 `PHOTO_DB_*` 配置。
- 当前照片库只支持 SQL Server。
- 照片文件下载可以通过 `PHOTO_FILE_BASE_URL` 代理，前端访问 `/api/photo/file` 或 `/api/photo-cache`，不直接依赖文件服务器。

群测群防源库兼容配置：

- `SQLSERVER_*` 和 `HCS_QMQF_SOURCE` 仍保留，用于兼容群测群防相关历史逻辑。
- 当前 v3 的主查询优先看 `DB_PROVIDER/DB_*`，照片补充看 `PHOTO_DB_*`。

## 后端环境变量

在 `backend/.env` 中配置。`.env` 不提交到 Git，下面只是示例。

### 主业务库为达梦

```env
DB_PROVIDER=dm
DB_HOST=你的达梦主机
DB_PORT=5236
DB_USER=你的用户名
DB_PASSWORD=你的密码
DB_SCHEMA=
```

也兼容旧字段：

```env
DM_HOST=你的达梦主机
DM_PORT=5236
DM_USER=你的用户名
DM_PASSWORD=你的密码
```

### 主业务库为 SQL Server

```env
DB_PROVIDER=sqlserver
DB_HOST=你的SQLServer主机
DB_PORT=1433
DB_NAME=你的数据库名
DB_USER=你的用户名
DB_PASSWORD=你的密码
DB_SQLSERVER_TRANSPORT=pytds
DB_SCHEMA=
DB_TRUST_CERT=true
DB_ENCRYPT=false
```

如果需要走 ODBC：

```env
DB_SQLSERVER_TRANSPORT=pyodbc
DB_DRIVER=ODBC Driver 18 for SQL Server
```

### 现场照片库

```env
PHOTO_DB_PROVIDER=sqlserver
PHOTO_DB_HOST=照片库SQLServer主机
PHOTO_DB_PORT=1433
PHOTO_DB_NAME=照片库数据库名
PHOTO_DB_USER=你的用户名
PHOTO_DB_PASSWORD=你的密码
PHOTO_DB_SQLSERVER_TRANSPORT=pytds
PHOTO_FILE_BASE_URL=http://文件服务器地址
PHOTO_DOWNLOAD_TIMEOUT=12
```

### 模型配置

通用模型配置：

```env
OPENAI_API_KEY=你的模型Key
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=你的OpenAI兼容接口地址
```

查询阶段模型：

```env
QUERY_PROVIDER=openai
QUERY_API_KEY=你的查询模型Key
QUERY_MODEL=gpt-4o-mini
QUERY_BASE_URL=你的查询模型Base URL
QUERY_THINKING_ENABLED=false
```

报告阶段模型：

```env
REPORT_PROVIDER=deepseek
REPORT_API_KEY=你的报告模型Key
REPORT_MODEL=deepseek-v4-flash
REPORT_BASE_URL=https://api.deepseek.com
REPORT_THINKING_ENABLED=true
REPORT_REASONING_EFFORT=high
```

### 语音转写

```env
ASR_MODEL=small
ASR_DEVICE=cpu
ASR_COMPUTE_TYPE=int8
```

### 调试表范围

```env
HCS_INCLUDE_TABLES=tb_hcs_monitoring,geo_gqp_jbxx
```

不配置时，系统会根据问题和 schema 知识自动选择候选表。

## 启动方式

### 1. 后端

建议使用已有的 `dm` Conda 环境：

```bash
conda activate dm
cd /home/lzb/projects/lm-dm8/backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

健康检查：

```text
http://127.0.0.1:8000/api/health
```

FastAPI 文档：

```text
http://127.0.0.1:8000/docs
```

注意：如果前端运行在 `https://10.61.48.10:5173`，那是 Vite 前端地址，不是 FastAPI 地址。接口文档要访问后端端口 `8000`。

### 2. 前端

```bash
cd /home/lzb/projects/lm-dm8/frontend
npm install
npm run dev:https
```

访问：

```text
https://localhost:5173/
```

局域网手机访问时，用开发机 IP：

```text
https://10.61.48.10:5173/
```

前端开发服务会把 `/api` 代理到后端。如果是 Android App 或需要指定后端地址，配置 `frontend/.env.local`：

```env
VITE_API_BASE_URL=http://10.61.48.10:8000
```

### 3. Android App

```bash
cd /home/lzb/projects/lm-dm8/frontend
npm run android:sync
npm run android:open
```

生成 debug APK：

```bash
cd /home/lzb/projects/lm-dm8/frontend/android
./gradlew assembleDebug
```

输出位置：

```text
frontend/android/app/build/outputs/apk/debug/app-debug.apk
```

## 关键接口

所有业务接口都挂在 `/api` 下。

```text
GET  /api/health                       健康检查
POST /api/query                        非流式自然语言查询
POST /api/query/stream                 SSE 流式自然语言查询，前端主要使用
POST /api/asr                          移动端录音转文字
GET  /api/displacement/recent-large    近期专业监测位移看板
GET  /api/qmqf/abnormal-dashboard      群测群防异常看板
GET  /api/report/asset-inventory       月报内容资产清单
GET  /api/report/stability-assets      月报稳定性评价和现场照片资产
GET  /api/photo/file                   现场照片/视频代理下载
GET  /api/photo-cache                  现场照片缓存与缩略图
```

## 查询工作流

用户提问进入后端后的主链路：

```text
前端输入
  -> POST /api/query/stream
  -> normalize_query_text()
  -> stream_agent_events()
  -> route_question()
  -> 根据路由选择处理路径
     -> clarify/out_of_scope：直接返回澄清或拒答
     -> template_query：执行稳定 SQL 模板或业务看板函数
     -> db_query/result_analysis：选择候选表，调用 LangChain SQL Agent
  -> 查询主业务库
  -> 按需补充现场照片附件
  -> 生成业务摘要/报告
  -> SSE 分段返回给前端
```

更完整的工作流图在：

[docs/diagrams/workflows/README.md](/home/lzb/projects/lm-dm8/docs/diagrams/workflows/README.md)

包含：

- `backend-overall-workflow.svg`：用户提问后的后端整体链路。
- `backend-routing-functions.svg`：路由判断阶段函数关系。
- `backend-api-interface-flow.svg`：后端 API 接口流动关系。
- `backend-api-interface-flow.md`：后端接口职责说明表。

## schema 知识文件

系统以真实数据库导出的 schema 作为主要依据，设计文档仅作为参考。

核心文件：

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

常用脚本：

```bash
cd /home/lzb/projects/lm-dm8/backend
python scripts/export_and_compare_schema.py
python scripts/generate_explained_schema.py
python scripts/profile_business_schema.py
python scripts/export_enum_review.py
```

## Agent 效果测试

评测说明：

[backend/evals/agent_effectiveness/README.md](/home/lzb/projects/lm-dm8/backend/evals/agent_effectiveness/README.md)

完整评测：

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

## 常见问题

### 为什么访问 `https://10.61.48.10:5173/docs` 进不了接口文档？

`5173` 是前端 Vite 端口，FastAPI 文档在后端端口。请访问：

```text
http://10.61.48.10:8000/docs
```

如果后端没有启 HTTPS，不要用 `https://10.61.48.10:8000/docs`。

### 为什么同一个问题有时结果不一样？

系统已经加入问题归一化、稳定 SQL 模板、SQL 缓存和问题路由，但普通 Agent 查询仍可能受模型输出影响。高频业务问题建议继续沉淀到 `backend/app/nlq/business_queries.py` 的确定性模板里。

缓存文件：

```text
backend/runtime/query_sql_cache.json
```

### 为什么现场照片有些 404？

照片记录来自数据库，真实文件需要能从 `PHOTO_FILE_BASE_URL` 或文件服务器访问。如果数据库中存在路径但文件服务器没有对应文件，后端会返回 404；这是数据源和文件存储不一致问题，不是前端渲染问题。

### 这个项目算多 Agent 吗？

当前更准确的定位是“单 Agent + 业务路由 + 稳定模板 + 多数据服务”的智能查询系统。它体现了 Agentic workflow，但还不是严格意义上的多 Agent 协作系统。
