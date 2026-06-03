# 后端 API 接口流转说明

后端入口统一在 `app/main.py`，所有接口都挂载在 `/api` 前缀下，具体路由在 `app/api/routes.py`。

| 接口 | 方法 | 主要处理 | 调用模块 | 主要数据源/外部资源 | 返回 |
|---|---|---|---|---|---|
| `/api/health` | GET | 健康检查 | `health()` | 无 | `{status: "ok"}` |
| `/api/query/stream` | POST | 主聊天问答接口，SSE 流式返回进度、报告和最终数据 | `stream_agent_events()` -> `run_agent()` | 达梦主库、SQL Server 照片库、LLM | SSE progress/summary/final |
| `/api/query` | POST | 非流式问答接口，主要用于调试或 Android 原生网络兜底 | `run_agent()` -> `sanitize_query_result()` | 达梦主库、SQL Server 照片库、LLM | 查询报告、表格、附件 |
| `/api/asr` | POST | 移动端录音转文字 | `transcribe_base64_audio()` | 本地 faster-whisper 模型 | `{text, error}` |
| `/api/photo/file` | GET | 代理下载现场照片/视频文件 | `download_photo_file()` | 照片文件服务器 `PHOTO_FILE_BASE_URL` | 图片/视频二进制 |
| `/api/photo-cache` | GET | 缓存并压缩远程照片，减少手机端加载压力 | `get_cached_photo_response()` | 照片文件服务器、本地缓存目录 | 缩略图文件响应 |
| `/api/displacement/recent-large` | GET | 近期专业监测位移较大对象看板 | `get_recent_displacement_dashboard()` | 达梦主库、月报生成资产 | 看板 JSON |
| `/api/qmqf/abnormal-dashboard` | GET | 群测群防异常看板 | `get_qmqf_abnormal_dashboard()` | SQL Server 群测群防源库 | 看板 JSON |
| `/api/report/asset-inventory` | GET | 月报资产清单统计 | `get_report_asset_inventory()` | 达梦主库/月报资产表 | 资产清单 JSON |
| `/api/report/stability-assets` | GET | 近期月报稳定性评价与现场照片资产 | `get_recent_report_stability_assets()` | 达梦主库/月报资产表 | 稳定性评价 JSON |

## 主问答接口内部流动

`/api/query/stream` 和 `/api/query` 的核心逻辑是同一个 `run_agent()`：

```text
routes.py
  -> normalize_query_text()
  -> stream_agent_events() 或 run_agent()
      -> normalize_query_question()
      -> normalize_history()
      -> route_question()
          -> _safety_route_question()
          -> _invoke_router_llm()
          -> _decision_from_llm_payload()
          -> _fallback_route_question()
      -> resolve_effective_question()
      -> 照片链路 / 稳定模板 SQL / 普通 SQL Agent 查询
      -> analyze_query_result()
      -> 返回 summary、columns、rows、attachments
```

## 数据库分工

- 达梦主业务库：普通高切坡业务查询、NL2SQL 主查询、部分看板/月报资产。
- SQL Server 照片库：现场照片/视频附件路径、群测群防源数据。
- 照片文件服务器：真正的图片/视频二进制文件下载。

