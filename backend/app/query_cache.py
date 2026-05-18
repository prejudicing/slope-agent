"""稳定查询口径缓存。

同一个自然语言问题在第一次成功生成并执行 SQL 后，会把 SQL 保存下来。
之后相同问题优先复用已验证 SQL，避免每次都让 LLM 重新选择表和字段导致结果漂移。
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from app.question_normalizer import normalize_query_question


ROOT_DIR = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT_DIR / "backend" / "runtime"
CACHE_PATH = CACHE_DIR / "query_sql_cache.json"
_LOCK = Lock()


def normalize_question(question: str) -> str:
    """统一问题文本，减少空格、换行等输入差异对缓存命中的影响。"""
    return " ".join(normalize_query_question(question).split())


def cache_key(question: str) -> str:
    """用哈希作为缓存 key，避免中文问题直接作为 JSON 顶层键过长。"""
    normalized = normalize_question(question)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _read_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_cache(cache: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def get_cached_sql(question: str) -> str:
    """读取完全相同问题对应的已验证 SQL。"""
    key = cache_key(question)
    with _LOCK:
        item = _read_cache().get(key) or {}
    if item.get("question") != normalize_question(question):
        return ""
    return item.get("sql", "")


def save_cached_sql(question: str, sql: str) -> None:
    """保存问题到 SQL 的稳定映射。"""
    if not question.strip() or not sql.strip():
        return

    key = cache_key(question)
    with _LOCK:
        cache = _read_cache()
        cache[key] = {
            "question": normalize_question(question),
            "sql": sql.strip(),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        _write_cache(cache)
