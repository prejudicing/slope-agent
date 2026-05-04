"""应用配置。

配置来自 backend/.env 或运行环境变量，包括达梦数据库和大模型接口信息。
"""

import os
from dotenv import load_dotenv

load_dotenv()

DM_USER = os.getenv("DM_USER")
DM_PASSWORD = os.getenv("DM_PASSWORD")
DM_HOST = os.getenv("DM_HOST")
DM_PORT = os.getenv("DM_PORT")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_ASR_MODEL = os.getenv("OPENAI_ASR_MODEL", "whisper-1")

# 可选：用逗号分隔覆盖默认高切坡业务表，主要用于临时调试。
HCS_INCLUDE_TABLES = os.getenv("HCS_INCLUDE_TABLES")
