"""应用配置。

配置来自 backend/.env 或运行环境变量，包括：
1. 达梦数据库；
2. 查询阶段模型；
3. 报告生成阶段模型；
4. 本地语音转写模型。

查询阶段和报告阶段允许使用同一套 OpenAI 兼容服务，也允许拆成两套独立配置。
"""

import os
from dotenv import load_dotenv

load_dotenv()

# 达梦数据库连接配置：项目主要业务数据都从这里读取。
DM_USER = os.getenv("DM_USER")
DM_PASSWORD = os.getenv("DM_PASSWORD")
DM_HOST = os.getenv("DM_HOST")
DM_PORT = os.getenv("DM_PORT")

# 通用聊天模型配置：作为查询阶段和报告阶段的默认回退。
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")

# 查询阶段模型：优先保证 SQL Agent 工具调用稳定，默认关闭 thinking。
QUERY_API_KEY = os.getenv("QUERY_API_KEY") or OPENAI_API_KEY
QUERY_MODEL = os.getenv("QUERY_MODEL") or OPENAI_MODEL
QUERY_BASE_URL = os.getenv("QUERY_BASE_URL") or OPENAI_BASE_URL
QUERY_PROVIDER = os.getenv("QUERY_PROVIDER", "auto").lower()
QUERY_THINKING_ENABLED = os.getenv("QUERY_THINKING_ENABLED", "false").lower() == "true"

# 报告阶段模型：允许保留思考模式，但默认只用 high，不放大到更重推理。
REPORT_API_KEY = os.getenv("REPORT_API_KEY") or OPENAI_API_KEY
REPORT_MODEL = os.getenv("REPORT_MODEL") or OPENAI_MODEL
REPORT_BASE_URL = os.getenv("REPORT_BASE_URL") or OPENAI_BASE_URL
REPORT_PROVIDER = os.getenv("REPORT_PROVIDER", "auto").lower()
REPORT_THINKING_ENABLED = os.getenv("REPORT_THINKING_ENABLED", "true").lower() == "true"
REPORT_REASONING_EFFORT = os.getenv("REPORT_REASONING_EFFORT", "high")

# 本地语音转写默认使用 faster-whisper；模型名称可以是 tiny/base/small/medium/large-v3，
# 也可以是本地模型目录。
ASR_MODEL = os.getenv("ASR_MODEL", "small")
ASR_DEVICE = os.getenv("ASR_DEVICE", "cpu")
ASR_COMPUTE_TYPE = os.getenv("ASR_COMPUTE_TYPE", "int8")

# 可选：用逗号分隔覆盖默认高切坡业务表，主要用于临时调试。
HCS_INCLUDE_TABLES = os.getenv("HCS_INCLUDE_TABLES")
