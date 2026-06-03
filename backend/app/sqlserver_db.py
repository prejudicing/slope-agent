"""SQL Server access for source-system group-monitoring data."""

from __future__ import annotations

from typing import Any

from app.config import (
    SQLSERVER_DATABASE,
    SQLSERVER_DRIVER,
    SQLSERVER_HOST,
    SQLSERVER_PASSWORD,
    SQLSERVER_PORT,
    SQLSERVER_USER,
)


DISPLAY_ROW_LIMIT = 50


def _require_sqlserver_config() -> None:
    missing = [
        name
        for name, value in {
            "SQLSERVER_HOST": SQLSERVER_HOST,
            "SQLSERVER_PORT": SQLSERVER_PORT,
            "SQLSERVER_DATABASE": SQLSERVER_DATABASE,
            "SQLSERVER_USER": SQLSERVER_USER,
            "SQLSERVER_PASSWORD": SQLSERVER_PASSWORD,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"缺少 SQL Server 配置: {', '.join(missing)}")


def _connect_pytds():
    import pytds

    return pytds.connect(
        server=SQLSERVER_HOST,
        port=int(SQLSERVER_PORT or 1433),
        database=SQLSERVER_DATABASE,
        user=SQLSERVER_USER,
        password=SQLSERVER_PASSWORD,
        timeout=30,
        login_timeout=10,
        as_dict=False,
    )


def _connect_pyodbc():
    import pyodbc

    security_options = "Encrypt=no;"
    if "ODBC Driver" in SQLSERVER_DRIVER:
        security_options += "TrustServerCertificate=yes;"
    conn_str = (
        f"DRIVER={{{SQLSERVER_DRIVER}}};"
        f"SERVER={SQLSERVER_HOST},{SQLSERVER_PORT};"
        f"DATABASE={SQLSERVER_DATABASE};"
        f"UID={SQLSERVER_USER};"
        f"PWD={SQLSERVER_PASSWORD};"
        f"{security_options}"
    )
    return pyodbc.connect(conn_str, timeout=10)


def _connect_pymssql():
    import pymssql

    return pymssql.connect(
        server=SQLSERVER_HOST,
        port=int(SQLSERVER_PORT or 1433),
        user=SQLSERVER_USER,
        password=SQLSERVER_PASSWORD,
        database=SQLSERVER_DATABASE,
        login_timeout=10,
        timeout=30,
        charset="utf8",
    )


def get_sqlserver_connection():
    _require_sqlserver_config()
    errors = []
    for factory in (_connect_pytds, _connect_pyodbc, _connect_pymssql):
        try:
            return factory()
        except Exception as exc:
            errors.append(f"{factory.__name__}: {exc}")
    raise RuntimeError("SQL Server 连接失败；" + " | ".join(errors))


def query_sqlserver_for_display(sql: str, display_limit: int = DISPLAY_ROW_LIMIT) -> tuple[list[str], list[dict], int]:
    """Execute source SQL Server SQL and return columns/rows for the UI.

    SQL Server cannot wrap every CTE query in a subquery for counting, so this
    function fetches a bounded sample and reports whether there are more rows.
    """
    conn = get_sqlserver_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [column[0] for column in cursor.description or []]
        raw_rows = cursor.fetchmany(display_limit + 1)
        has_more = len(raw_rows) > display_limit
        rows = [_row_to_dict(columns, row) for row in raw_rows[:display_limit]]
        total_rows = display_limit + 1 if has_more else len(rows)
        return columns, rows, total_rows
    finally:
        conn.close()


def _row_to_dict(columns: list[str], row: Any) -> dict:
    values = list(row)
    return {column: _serialize_cell(values[index]) for index, column in enumerate(columns)}


def _serialize_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
