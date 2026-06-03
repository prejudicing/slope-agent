"""应用配置。

配置来自 backend/.env 或运行环境变量，包括：
1. 数据库连接（支持 dm 与 sqlserver）；
2. 查询阶段模型；
3. 报告生成阶段模型；
4. 本地语音转写模型。

查询阶段和报告阶段允许使用同一套 OpenAI 兼容服务，也允许拆成两套独立配置。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")

# 通用数据库连接配置。默认仍兼容旧的达梦环境变量，便于平滑迁移到 SQL Server。
DB_PROVIDER = os.getenv("DB_PROVIDER", "dm").strip().lower()
DB_HOST = os.getenv("DB_HOST") or os.getenv("DM_HOST")
DB_PORT = os.getenv("DB_PORT") or os.getenv("DM_PORT")
DB_NAME = os.getenv("DB_NAME", "").strip()
DB_USER = os.getenv("DB_USER") or os.getenv("DM_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("DM_PASSWORD")
# SQL Server 连接优先走非 ODBC 的 pytds 方案；若需要兼容旧环境，可切回 pyodbc。
DB_SQLSERVER_TRANSPORT = os.getenv("DB_SQLSERVER_TRANSPORT", "pytds").strip().lower()
DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server").strip()
DB_SCHEMA = os.getenv("DB_SCHEMA", "").strip()
DB_TRUST_CERT = os.getenv("DB_TRUST_CERT", "true").lower() == "true"
DB_ENCRYPT = os.getenv("DB_ENCRYPT", "false").lower() == "true"
DB_EXTRA_PARAMS = os.getenv("DB_EXTRA_PARAMS", "").strip()

# 保留旧达梦字段，避免已有脚本和环境一次性全部切换时断掉。
DM_USER = DB_USER if DB_PROVIDER == "dm" else os.getenv("DM_USER")
DM_PASSWORD = DB_PASSWORD if DB_PROVIDER == "dm" else os.getenv("DM_PASSWORD")
DM_HOST = DB_HOST if DB_PROVIDER == "dm" else os.getenv("DM_HOST")
DM_PORT = DB_PORT if DB_PROVIDER == "dm" else os.getenv("DM_PORT")

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

HCS_QMQF_SOURCE = os.getenv("HCS_QMQF_SOURCE", "dm").lower()
SQLSERVER_HOST = os.getenv("SQLSERVER_HOST")
SQLSERVER_PORT = os.getenv("SQLSERVER_PORT", "1433")
SQLSERVER_DATABASE = os.getenv("SQLSERVER_DATABASE", "hcsmonitor")
SQLSERVER_USER = os.getenv("SQLSERVER_USER")
SQLSERVER_PASSWORD = os.getenv("SQLSERVER_PASSWORD")
SQLSERVER_DRIVER = os.getenv("SQLSERVER_DRIVER", "SQL Server")

# 照片库配置：主业务查询仍走 DB_*，现场照片路径单独从 SQL Server 补充。
PHOTO_DB_PROVIDER = os.getenv("PHOTO_DB_PROVIDER", "sqlserver").strip().lower()
PHOTO_DB_HOST = os.getenv("PHOTO_DB_HOST")
PHOTO_DB_PORT = os.getenv("PHOTO_DB_PORT", "1433").strip()
PHOTO_DB_NAME = os.getenv("PHOTO_DB_NAME", "").strip()
PHOTO_DB_USER = os.getenv("PHOTO_DB_USER")
PHOTO_DB_PASSWORD = os.getenv("PHOTO_DB_PASSWORD")
PHOTO_DB_SQLSERVER_TRANSPORT = os.getenv(
    "PHOTO_DB_SQLSERVER_TRANSPORT",
    "pytds",
).strip().lower()
PHOTO_DB_DRIVER = os.getenv("PHOTO_DB_DRIVER", DB_DRIVER).strip()
PHOTO_DB_TRUST_CERT = os.getenv("PHOTO_DB_TRUST_CERT", "true").lower() == "true"
PHOTO_DB_ENCRYPT = os.getenv("PHOTO_DB_ENCRYPT", "false").lower() == "true"
PHOTO_DB_EXTRA_PARAMS = os.getenv("PHOTO_DB_EXTRA_PARAMS", "").strip()
PHOTO_FILE_BASE_URL = os.getenv("PHOTO_FILE_BASE_URL", "").strip().rstrip("/")
PHOTO_DOWNLOAD_TIMEOUT = float(os.getenv("PHOTO_DOWNLOAD_TIMEOUT", "12"))
