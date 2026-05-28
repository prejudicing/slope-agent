"""Pure Python SQL Server connection smoke test.

Reads backend/.env, connects with python-tds, and prints a few harmless
metadata queries. This script does not use SQLAlchemy or LangChain.

Run from repo root:
    python backend/scripts/test_sqlserver_connection.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytds
from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BACKEND_DIR / ".env"


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int_env(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value else default


def main() -> None:
    load_dotenv(ENV_PATH)

    provider = _env("PHOTO_DB_PROVIDER", _env("DB_PROVIDER", "dm")).lower()
    if provider != "sqlserver":
        raise RuntimeError(f"PHOTO_DB_PROVIDER is {provider!r}, expected 'sqlserver'.")

    host = _env("PHOTO_DB_HOST", _env("DB_HOST"))
    port = _int_env("PHOTO_DB_PORT", _int_env("DB_PORT", 1433))
    database = _env("PHOTO_DB_NAME", _env("DB_NAME"))
    user = _env("PHOTO_DB_USER", _env("DB_USER"))
    password = _env("PHOTO_DB_PASSWORD", _env("DB_PASSWORD"))

    missing = [
        name
        for name, value in {
            "PHOTO_DB_HOST": host,
            "PHOTO_DB_NAME": database,
            "PHOTO_DB_USER": user,
            "PHOTO_DB_PASSWORD": password,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError("Missing required env vars: " + ", ".join(missing))

    print(f"Connecting to SQL Server {host}:{port}, database={database}, user={user}")

    with pytds.connect(
        server=host,
        port=port,
        database=database,
        user=user,
        password=password,
        autocommit=True,
        timeout=10,
        login_timeout=10,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  DB_NAME() AS current_database,
                  SUSER_SNAME() AS login_name,
                  @@VERSION AS server_version
                """
            )
            current_database, login_name, server_version = cur.fetchone()
            print("\nConnection OK")
            print(f"Current database: {current_database}")
            print(f"Login name: {login_name}")
            print(f"Server version: {server_version}")

            cur.execute(
                """
                SELECT TOP 20
                  TABLE_SCHEMA,
                  TABLE_NAME
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE = 'BASE TABLE'
                ORDER BY TABLE_SCHEMA, TABLE_NAME
                """
            )
            rows = cur.fetchall()

    print("\nFirst tables:")
    if not rows:
        print("(No base tables visible to this user.)")
        return

    for schema_name, table_name in rows:
        print(f"- {schema_name}.{table_name}")


if __name__ == "__main__":
    main()
