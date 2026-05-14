"""应用配置。

配置来自 backend/.env 或运行环境变量，包括达梦数据库、查询模型和本地语音转写模型。
查询模型仍可使用任意 OpenAI 兼容接口；语音转写默认使用本地 ASR。
"""

import os
from dotenv import load_dotenv

load_dotenv()

# 达梦数据库连接配置：项目主要业务数据都从这里读取。
DM_USER = os.getenv("DM_USER")
DM_PASSWORD = os.getenv("DM_PASSWORD")
DM_HOST = os.getenv("DM_HOST")
DM_PORT = os.getenv("DM_PORT")

# 查询总结仍可使用任意 OpenAI 兼容接口，只要它支持聊天补全即可。
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")

# 本地语音转写默认使用 faster-whisper；模型名称可以是 tiny/base/small/medium/large-v3，
# 也可以是本地模型目录。
ASR_MODEL = os.getenv("ASR_MODEL", "small")
ASR_DEVICE = os.getenv("ASR_DEVICE", "cpu")
ASR_COMPUTE_TYPE = os.getenv("ASR_COMPUTE_TYPE", "int8")

# 可选：用逗号分隔覆盖默认高切坡业务表，主要用于临时调试。
HCS_INCLUDE_TABLES = os.getenv("HCS_INCLUDE_TABLES")
