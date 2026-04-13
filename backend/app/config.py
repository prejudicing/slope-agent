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

# Optional comma-separated override for high-cut-slope business tables.
HCS_INCLUDE_TABLES = os.getenv("HCS_INCLUDE_TABLES")
