# 高切坡系统智能查询 Agent

一个面向高切坡业务的自然语言查询系统。  
用户可以直接输入中文问题，系统结合真实数据库 schema、业务解释和 SQL Agent，自动生成 SQL、查询达梦数据库，并返回：

- 生成 SQL
- 查询结果表格
- 查询总结
- Agent 思考过程 / 日志
- 结果语音播报

## 当前能力

- 支持高切坡基础信息、群测群防、专业监测、预警专报、巡查记录、空间资料等业务查询
- 支持流式展示 Agent 查询过程
- 支持中文语音输入
- 支持查询结果中文播报，带开始 / 暂停 / 继续 / 停止按钮
- 支持基于真实数据库导出的 schema 知识增强
- 对部分高频关键问题提供稳定业务查询模板
- 对同一句自然语言问题支持 SQL 口径缓存，减少重复提问结果漂移

## 项目结构

```text
lm-dm8/
├─ backend/
│  ├─ app/
│  │  ├─ agent.py                 # Agent 主流程、流式事件、结果表格回查
│  │  ├─ api.py                   # FastAPI 查询接口
│  │  ├─ business_queries.py      # 高频问题确定性 SQL 模板
│  │  ├─ config.py                # 环境变量配置
│  │  ├─ db.py                    # 达梦数据库连接
│  │  ├─ domain.py                # Agent Prompt 和业务边界
│  │  ├─ main.py                  # FastAPI 应用入口
│  │  ├─ query_cache.py           # 问题 -> SQL 稳定缓存
│  │  └─ schema_knowledge.py      # schema 知识召回和候选表选择
│  ├─ runtime/
│  │  └─ query_sql_cache.json     # 运行时 SQL 缓存
│  ├─ schema_exports/             # 真实库 schema 导出和解释结果
│  ├─ scripts/                    # schema 导出、解释、画像脚本
│  └─ requirements.txt
├─ frontend/
│  ├─ src/
│  │  ├─ components/              # Vue 组件
│  │  ├─ api/                     # 前端请求
│  │  ├─ types/                   # TS 类型
│  │  ├─ App.vue
│  │  └─ main.ts
│  ├─ scripts/
│  │  └─ create-dev-cert.mjs      # 本地 HTTPS 证书生成
│  ├─ package.json
│  └─ vite.config.ts
├─ docs/                          # 阶段总结、图、提示词等文档
└─ 高切坡数据库设计文档.docx       # 历史设计文档，仅作为参考
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
- Element Plus
- Web Speech API（中文语音输入）
- SpeechSynthesis（结果播报）

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

在 `backend/.env` 中配置：

```env
DM_USER=你的达梦用户名
DM_PASSWORD=你的达梦密码
DM_HOST=你的达梦主机
DM_PORT=5236

OPENAI_API_KEY=你的模型接口 Key
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=你的模型接口 Base URL
```

可选项：

```env
HCS_INCLUDE_TABLES=tb_hcs_monitoring,geo_gqp_jbxx
```

如果不配置 `HCS_INCLUDE_TABLES`，系统会优先根据问题从 schema 知识中自动选择候选表。

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
https://10.61.48.10:5173/
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

## 前端命令

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

预览构建结果：

```bash
npm run preview
```

## 后端命令

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

系统当前以真实数据库导出的 schema 作为主要依据，设计文档仅作为历史参考。

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
```

用途概览：

- `database_schema.json`：真实数据库表结构
- `document_schema.json`：Word 文档提取结果
- `schema_comparison.json`：设计文档与真实数据库差异
- `database_schema_explained.json`：带中文业务解释的 schema
- `schema_chunks.jsonl`：适合后续接向量库的 chunk
- `table_profile.json`：真实表画像
- `core_table_candidates.json`：核心表候选
- `business_starter_pack.json`：Agent 初始业务知识包

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

## 当前系统行为说明

### 1. 查询结果和查询总结分离

- 查询结果表格来自真实 SQL 查询返回的 `columns` 和 `rows`
- 查询总结来自 Agent Final Answer 或稳定模板总结

### 2. 稳定 SQL 缓存

系统会把“相同自然语言问题 -> 已验证 SQL”保存到：

```text
backend/runtime/query_sql_cache.json
```

这样重复提问时，可以复用稳定查询口径，减少结果漂移。

如需清空缓存：

```bash
rm /home/lzb/projects/lm-dm8/backend/runtime/query_sql_cache.json
```

### 3. 高频稳定业务模板

对部分关键问题，系统不会交给 LLM 自由发挥，而是走确定性 SQL 模板。例如：

- 异常状态 + 异常类型

这类问题会优先从群测群防监测记录中识别：

- 裂缝
- 落石
- 坡面破坏
- 挡墙或道路开裂
- 排水沟堵塞
- 排水口堵塞
- 监测设施异常
- 坡周乱搭乱堆

## 语音功能说明

### 中文语音输入

- 入口：查询输入框右侧“中文语音输入”
- 浏览器要求：通常需要 `HTTPS` 或 `localhost`
- 推荐浏览器：Chrome / Edge
- 手机访问时需要连接同一局域网

### 查询结果播报

- 支持开始播报 / 暂停 / 继续 / 停止
- 播报内容包括查询总结和前几条表格结果
- 使用浏览器内置 `speechSynthesis`

## 文档目录

项目文档位于：

[docs/README.md](/home/lzb/projects/lm-dm8/docs/README.md)

包括：

- 阶段总结
- 查询流程图
- 业务逻辑图
- 提示词
- 开发记录

## 常见问题

### 1. 为什么手机上语音输入没反应？

优先检查：

- 是否使用了 HTTPS 地址
- 是否点击了继续访问自签名证书页面
- 是否已授权麦克风
- 是否和开发机在同一局域网

### 2. 为什么同一个问题有时结果不一样？

当前系统已经增加：

- 稳定 SQL 缓存
- 确定性 schema 排序
- 高频问题稳定模板

如果需要重新生成 SQL，可以删除：

```bash
rm /home/lzb/projects/lm-dm8/backend/runtime/query_sql_cache.json
```

### 3. 为什么设计文档中的表在数据库里找不到？

因为当前项目已经验证过：数据库设计文档和真实达梦数据库并不完全一致。  
系统现在以真实数据库导出的 schema 为准，设计文档仅保留作历史参考。

## 后续建议

- 建立高频问题回归测试集
- 继续完善 schema 业务解释
- 引入向量数据库做 Schema RAG
- 完善异常类型、预警口径、状态枚举的业务映射
- 增加更稳定的结果展示别名和枚举翻译
