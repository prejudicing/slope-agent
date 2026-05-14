"""达梦数据库连接与 LangChain SQLDatabase 初始化。"""

from urllib.parse import quote_plus
from sqlalchemy import create_engine, inspect
from langchain_community.utilities import SQLDatabase
from app.config import DM_USER, DM_PASSWORD, DM_HOST, DM_PORT, HCS_INCLUDE_TABLES
from app.domain import GQP_INCLUDE_TABLES
from app.schema_knowledge import get_default_core_tables


def _require_dm_config():
    """启动查询前校验必要的达梦连接配置。"""
    missing = [
        name
        for name, value in {
            "DM_USER": DM_USER,
            "DM_PASSWORD": DM_PASSWORD,
            "DM_HOST": DM_HOST,
            "DM_PORT": DM_PORT,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"缺少达梦数据库配置: {', '.join(missing)}")


def _resolve_existing_tables(uri: str, requested_tables: list[str]) -> tuple[list[str], list[str]]:
    """把候选表名解析为真实库中存在的表，过滤文档里有但库里没有的旧表。"""
    engine = create_engine(uri)
    try:
        inspector = inspect(engine)
        available_tables = inspector.get_table_names()
    finally:
        engine.dispose()

    available_by_lower = {table.lower(): table for table in available_tables}
    resolved_tables = []
    missing_tables = []

    for table in requested_tables:
        actual_table = available_by_lower.get(table.lower())
        if actual_table:
            resolved_tables.append(actual_table)
        else:
            missing_tables.append(table)

    if not resolved_tables:
        raise RuntimeError(
            "高切坡业务表未在当前数据库中找到。"
            f"配置表: {', '.join(requested_tables)}；"
            f"数据库可见表: {', '.join(available_tables[:50])}"
        )

    return resolved_tables, missing_tables


def get_db(include_tables: list[str] | None = None):
    """创建限定业务表范围的 SQLDatabase，降低 Agent 误查无关表的概率。"""
    _require_dm_config()
    password = quote_plus(DM_PASSWORD)
    # 优先使用问题召回的候选表；没有召回结果时再回退到环境变量或默认核心表。
    requested_tables = include_tables or (
        [table.strip() for table in HCS_INCLUDE_TABLES.split(",") if table.strip()]
        if HCS_INCLUDE_TABLES
        else get_default_core_tables() or GQP_INCLUDE_TABLES
    )

    uri = f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/"
    include_tables, missing_tables = _resolve_existing_tables(uri, requested_tables)

    if missing_tables:
        # 允许旧文档表“存在于候选中但不存在于真实库”；打印出来便于排查，不直接阻断查询。
        print(
            ">>> skip missing high-cut-slope tables: "
            + ", ".join(missing_tables)
        )

    db = SQLDatabase.from_uri(
        uri,
        include_tables=include_tables,
        sample_rows_in_table_info=1,
    )
    return db
