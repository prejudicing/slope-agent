"""数据库连接与 LangChain SQLDatabase 初始化。

当前支持：
- dm（达梦）
- sqlserver（SQL Server，默认走 pytds，也兼容 pyodbc）
"""

from __future__ import annotations

from urllib.parse import quote_plus

from langchain_community.utilities import SQLDatabase
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from app.config import (
    DB_DRIVER,
    DB_ENCRYPT,
    DB_EXTRA_PARAMS,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_PROVIDER,
    DB_SCHEMA,
    DB_SQLSERVER_TRANSPORT,
    DB_TRUST_CERT,
    DB_USER,
    HCS_INCLUDE_TABLES,
    PHOTO_DB_DRIVER,
    PHOTO_DB_ENCRYPT,
    PHOTO_DB_EXTRA_PARAMS,
    PHOTO_DB_HOST,
    PHOTO_DB_NAME,
    PHOTO_DB_PASSWORD,
    PHOTO_DB_PORT,
    PHOTO_DB_PROVIDER,
    PHOTO_DB_SQLSERVER_TRANSPORT,
    PHOTO_DB_TRUST_CERT,
    PHOTO_DB_USER,
)
from app.domain import GQP_INCLUDE_TABLES
from app.schema_knowledge import get_default_core_tables

SUPPORTED_DB_PROVIDERS = {"dm", "sqlserver"}


def _require_db_config() -> None:
    """启动查询前校验必要的数据库连接配置。"""
    if DB_PROVIDER not in SUPPORTED_DB_PROVIDERS:
        raise RuntimeError(
            f"当前数据库类型 {DB_PROVIDER!r} 暂不支持，请使用 dm 或 sqlserver。"
        )

    required = {
        "DB_USER": DB_USER,
        "DB_PASSWORD": DB_PASSWORD,
        "DB_HOST": DB_HOST,
    }
    if DB_PROVIDER == "dm":
        required["DB_PORT"] = DB_PORT
    if DB_PROVIDER == "sqlserver":
        required["DB_NAME"] = DB_NAME

    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"缺少数据库配置: {', '.join(missing)}")


def get_db_provider() -> str:
    return DB_PROVIDER


def build_db_uri() -> str:
    """构造 SQLAlchemy 可识别的数据库连接串。"""
    _require_db_config()
    password = quote_plus(DB_PASSWORD or "")
    user = quote_plus(DB_USER or "")

    if DB_PROVIDER == "dm":
        return f"dm+dmPython://{user}:{password}@{DB_HOST}:{DB_PORT}/"

    host = DB_HOST or ""
    if DB_PORT:
        host = f"{host}:{DB_PORT}"

    if DB_SQLSERVER_TRANSPORT == "pytds":
        query_parts = []
        if DB_EXTRA_PARAMS:
            query_parts.extend(
                part for part in DB_EXTRA_PARAMS.split("&") if "=" in part and part.strip()
            )
        query = f"?{'&'.join(query_parts)}" if query_parts else ""
        return f"mssql+pytds://{user}:{password}@{host}/{quote_plus(DB_NAME)}{query}"

    query_params = {
        "driver": DB_DRIVER,
        "TrustServerCertificate": "yes" if DB_TRUST_CERT else "no",
        "Encrypt": "yes" if DB_ENCRYPT else "no",
    }
    if DB_EXTRA_PARAMS:
        for part in DB_EXTRA_PARAMS.split("&"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            query_params[key] = value

    query = "&".join(
        f"{quote_plus(str(key))}={quote_plus(str(value))}"
        for key, value in query_params.items()
        if str(value)
    )
    return f"mssql+pyodbc://{user}:{password}@{host}/{quote_plus(DB_NAME)}?{query}"


def _build_sqlserver_uri(
    *,
    user_name: str | None,
    password_value: str | None,
    host_value: str | None,
    port_value: str | None,
    database_name: str,
    transport: str,
    driver: str,
    trust_cert: bool,
    encrypt: bool,
    extra_params: str,
) -> str:
    password = quote_plus(password_value or "")
    user = quote_plus(user_name or "")
    host = host_value or ""
    if port_value:
        host = f"{host}:{port_value}"

    if transport == "pytds":
        query_parts = [
            part for part in extra_params.split("&") if "=" in part and part.strip()
        ]
        query = f"?{'&'.join(query_parts)}" if query_parts else ""
        return f"mssql+pytds://{user}:{password}@{host}/{quote_plus(database_name)}{query}"

    query_params = {
        "driver": driver,
        "TrustServerCertificate": "yes" if trust_cert else "no",
        "Encrypt": "yes" if encrypt else "no",
    }
    if extra_params:
        for part in extra_params.split("&"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            query_params[key] = value

    query = "&".join(
        f"{quote_plus(str(key))}={quote_plus(str(value))}"
        for key, value in query_params.items()
        if str(value)
    )
    return f"mssql+pyodbc://{user}:{password}@{host}/{quote_plus(database_name)}?{query}"


def _require_photo_db_config() -> None:
    if PHOTO_DB_PROVIDER != "sqlserver":
        raise RuntimeError("照片库目前仅支持 sqlserver。")
    required = {
        "PHOTO_DB_HOST": PHOTO_DB_HOST,
        "PHOTO_DB_NAME": PHOTO_DB_NAME,
        "PHOTO_DB_USER": PHOTO_DB_USER,
        "PHOTO_DB_PASSWORD": PHOTO_DB_PASSWORD,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"缺少照片库配置: {', '.join(missing)}")


def build_photo_db_uri() -> str:
    """构造现场照片 SQL Server 库连接串。"""
    _require_photo_db_config()
    return _build_sqlserver_uri(
        user_name=PHOTO_DB_USER,
        password_value=PHOTO_DB_PASSWORD,
        host_value=PHOTO_DB_HOST,
        port_value=PHOTO_DB_PORT,
        database_name=PHOTO_DB_NAME,
        transport=PHOTO_DB_SQLSERVER_TRANSPORT,
        driver=PHOTO_DB_DRIVER,
        trust_cert=PHOTO_DB_TRUST_CERT,
        encrypt=PHOTO_DB_ENCRYPT,
        extra_params=PHOTO_DB_EXTRA_PARAMS,
    )


def get_photo_sqlalchemy_engine() -> Engine:
    """创建现场照片 SQL Server engine。"""
    return create_engine(build_photo_db_uri())


def get_sqlalchemy_engine() -> Engine:
    """创建数据库 engine。"""
    uri = build_db_uri()
    return create_engine(uri)


def get_default_schema() -> str | None:
    """返回数据库默认 schema；未配置时返回 None。"""
    return DB_SCHEMA or None


def get_sample_limit_clause(sample_limit: int) -> str:
    """返回不同数据库的样本限制语句片段。"""
    if sample_limit <= 0:
        return ""
    if DB_PROVIDER == "sqlserver":
        return f"TOP {sample_limit}"
    return ""


def _resolve_existing_tables(
    engine: Engine, requested_tables: list[str]
) -> tuple[list[str], list[str]]:
    """把候选表名解析为真实库中存在的表，过滤文档里有但库里没有的旧表。"""
    try:
        inspector = inspect(engine)
        available_tables = inspector.get_table_names(schema=get_default_schema())
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


def get_db(include_tables: list[str] | None = None) -> SQLDatabase:
    """创建限定业务表范围的 SQLDatabase，降低 Agent 误查无关表的概率。"""
    requested_tables = include_tables or (
        [table.strip() for table in HCS_INCLUDE_TABLES.split(",") if table.strip()]
        if HCS_INCLUDE_TABLES
        else get_default_core_tables() or GQP_INCLUDE_TABLES
    )

    engine = get_sqlalchemy_engine()
    include_tables, missing_tables = _resolve_existing_tables(engine, requested_tables)

    if missing_tables:
        print(">>> skip missing high-cut-slope tables: " + ", ".join(missing_tables))

    db = SQLDatabase(
        engine=engine,
        schema=get_default_schema(),
        include_tables=include_tables,
        sample_rows_in_table_info=1,
    )
    return db
