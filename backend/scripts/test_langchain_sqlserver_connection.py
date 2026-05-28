"""LangChain SQLDatabase SQL Server smoke test.

Reads backend/.env and exercises the same database layer used by the NL2SQL
agent: app.db -> SQLAlchemy engine -> LangChain SQLDatabase.

Run from repo root:
    conda run -n dm python backend/scripts/test_langchain_sqlserver_connection.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from langchain_community.utilities import SQLDatabase

from app.db import build_photo_db_uri, get_photo_sqlalchemy_engine


def _mask_uri(uri: str) -> str:
    if "://" not in uri or "@" not in uri:
        return uri
    prefix, rest = uri.split("://", 1)
    credentials, host_part = rest.split("@", 1)
    user = credentials.split(":", 1)[0]
    return f"{prefix}://{user}:***@{host_part}"


def main() -> None:
    uri = build_photo_db_uri()
    print("SQLAlchemy URI:", _mask_uri(uri))

    engine = get_photo_sqlalchemy_engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT
                      DB_NAME() AS current_database,
                      SUSER_SNAME() AS login_name,
                      @@VERSION AS server_version
                    """
                )
            ).one()
            print("\nSQLAlchemy connection OK")
            print(f"Current database: {row.current_database}")
            print(f"Login name: {row.login_name}")
            print(f"Server version: {row.server_version}")
    finally:
        engine.dispose()

    db = SQLDatabase(
        engine=get_photo_sqlalchemy_engine(),
        include_tables=["tb_hcs_monitoring"],
        sample_rows_in_table_info=1,
    )
    print("\nLangChain SQLDatabase OK")
    table_names = db.get_usable_table_names()
    print(f"Usable table count: {len(table_names)}")
    for table_name in table_names[:20]:
        print(f"- {table_name}")

    probe_table = "tb_hcs_monitoring" if "tb_hcs_monitoring" in table_names else table_names[0]
    result = db.run(f"SELECT TOP 3 * FROM {probe_table}")
    print(f"\nSample query OK: SELECT TOP 3 * FROM {probe_table}")
    print(str(result)[:1200])


if __name__ == "__main__":
    main()
