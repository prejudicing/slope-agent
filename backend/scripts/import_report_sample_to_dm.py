from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text


BACKEND_DIR = Path(__file__).resolve().parents[1]
SAMPLE_DIR = BACKEND_DIR / "report_extract_sample"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER  # noqa: E402


TABLES = (
    "ai_report_question_sample",
    "ai_report_asset_sample",
    "ai_report_page_sample",
    "ai_report_doc_sample",
)


def dm_engine():
    password = quote_plus(DM_PASSWORD)
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def clean(value, limit: int | None = None):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text_value = str(value).replace("\x00", "").strip()
    # dmPython on this machine uses a GBK client encoding. Replace rare
    # non-GBK symbols so one strange glyph does not block the whole import.
    text_value = text_value.encode("gbk", errors="replace").decode("gbk", errors="replace")
    if limit and len(text_value) > limit:
        return text_value[:limit]
    return text_value


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def table_exists(conn, table_name: str) -> bool:
    return bool(conn.execute(
        text("SELECT COUNT(*) FROM user_tables WHERE LOWER(table_name)=LOWER(:name)"),
        {"name": table_name},
    ).scalar())


def create_tables(conn):
    if not table_exists(conn, "ai_report_doc_sample"):
        conn.execute(text("""
            CREATE TABLE ai_report_doc_sample (
              file_hash VARCHAR(64) PRIMARY KEY,
              file_name VARCHAR(500),
              file_path VARCHAR(1000),
              file_ext VARCHAR(20),
              file_size BIGINT,
              county VARCHAR(100),
              report_year INT,
              report_month INT,
              report_type VARCHAR(100),
              title VARCHAR(800),
              text_length INT,
              page_count INT,
              image_count INT,
              table_count INT,
              chart_page_count INT,
              photo_page_count INT,
              table_page_count INT,
              parse_status VARCHAR(50),
              parse_message VARCHAR(1000),
              analyzed_at VARCHAR(30)
            )
        """))
    if not table_exists(conn, "ai_report_page_sample"):
        conn.execute(text("""
            CREATE TABLE ai_report_page_sample (
              page_id VARCHAR(80) PRIMARY KEY,
              file_hash VARCHAR(64),
              file_name VARCHAR(500),
              page_no INT,
              county VARCHAR(100),
              report_year INT,
              report_month INT,
              report_type VARCHAR(100),
              image_count INT,
              chart_score INT,
              photo_score INT,
              table_score INT,
              risk_score INT,
              asset_type VARCHAR(100),
              text_excerpt VARCHAR(4000),
              slope_codes VARCHAR(2000),
              monitor_points VARCHAR(2000)
            )
        """))
    if not table_exists(conn, "ai_report_asset_sample"):
        conn.execute(text("""
            CREATE TABLE ai_report_asset_sample (
              asset_id VARCHAR(100) PRIMARY KEY,
              file_hash VARCHAR(64),
              file_name VARCHAR(500),
              page_no INT,
              asset_index INT,
              asset_type VARCHAR(100),
              inferred_label VARCHAR(300),
              image_count_on_page INT,
              text_excerpt VARCHAR(4000),
              slope_codes VARCHAR(2000),
              monitor_points VARCHAR(2000)
            )
        """))
    if not table_exists(conn, "ai_report_question_sample"):
        conn.execute(text("""
            CREATE TABLE ai_report_question_sample (
              question_id VARCHAR(80) PRIMARY KEY,
              question VARCHAR(1000),
              expected_source VARCHAR(500),
              county VARCHAR(100),
              report_year INT,
              report_month INT,
              query_type VARCHAR(100),
              expected_asset_type VARCHAR(100),
              test_status VARCHAR(50),
              test_result VARCHAR(4000)
            )
        """))


def clear_tables(conn):
    for table_name in TABLES:
        if table_exists(conn, table_name):
            conn.execute(text(f"DELETE FROM {table_name}"))


def insert_docs(conn, rows):
    sql = text("""
        INSERT INTO ai_report_doc_sample (
          file_hash, file_name, file_path, file_ext, file_size, county, report_year, report_month,
          report_type, title, text_length, page_count, image_count, table_count, chart_page_count,
          photo_page_count, table_page_count, parse_status, parse_message, analyzed_at
        ) VALUES (
          :file_hash, :file_name, :file_path, :file_ext, :file_size, :county, :report_year, :report_month,
          :report_type, :title, :text_length, :page_count, :image_count, :table_count, :chart_page_count,
          :photo_page_count, :table_page_count, :parse_status, :parse_message, :analyzed_at
        )
    """)
    for row in rows:
        conn.execute(sql, {key: clean(row.get(key), 1000) for key in [
            "file_hash", "file_name", "file_path", "file_ext", "file_size", "county", "report_year",
            "report_month", "report_type", "title", "text_length", "page_count", "image_count",
            "table_count", "chart_page_count", "photo_page_count", "table_page_count", "parse_status",
            "parse_message", "analyzed_at",
        ]})


def insert_pages(conn, rows):
    sql = text("""
        INSERT INTO ai_report_page_sample (
          page_id, file_hash, file_name, page_no, county, report_year, report_month, report_type,
          image_count, chart_score, photo_score, table_score, risk_score, asset_type, text_excerpt,
          slope_codes, monitor_points
        ) VALUES (
          :page_id, :file_hash, :file_name, :page_no, :county, :report_year, :report_month, :report_type,
          :image_count, :chart_score, :photo_score, :table_score, :risk_score, :asset_type, :text_excerpt,
          :slope_codes, :monitor_points
        )
    """)
    for row in rows:
        conn.execute(sql, {
            "page_id": clean(row.get("page_id"), 80),
            "file_hash": clean(row.get("file_hash"), 64),
            "file_name": clean(row.get("file_name"), 500),
            "page_no": row.get("page_no"),
            "county": clean(row.get("county"), 100),
            "report_year": row.get("report_year"),
            "report_month": row.get("report_month"),
            "report_type": clean(row.get("report_type"), 100),
            "image_count": row.get("image_count"),
            "chart_score": row.get("chart_score"),
            "photo_score": row.get("photo_score"),
            "table_score": row.get("table_score"),
            "risk_score": row.get("risk_score"),
            "asset_type": clean(row.get("asset_type"), 100),
            "text_excerpt": clean(row.get("text_excerpt"), 3900),
            "slope_codes": clean(row.get("slope_codes"), 1900),
            "monitor_points": clean(row.get("monitor_points"), 1900),
        })


def insert_assets(conn, rows):
    sql = text("""
        INSERT INTO ai_report_asset_sample (
          asset_id, file_hash, file_name, page_no, asset_index, asset_type, inferred_label,
          image_count_on_page, text_excerpt, slope_codes, monitor_points
        ) VALUES (
          :asset_id, :file_hash, :file_name, :page_no, :asset_index, :asset_type, :inferred_label,
          :image_count_on_page, :text_excerpt, :slope_codes, :monitor_points
        )
    """)
    for row in rows:
        conn.execute(sql, {
            "asset_id": clean(row.get("asset_id"), 100),
            "file_hash": clean(row.get("file_hash"), 64),
            "file_name": clean(row.get("file_name"), 500),
            "page_no": row.get("page_no"),
            "asset_index": row.get("asset_index"),
            "asset_type": clean(row.get("asset_type"), 100),
            "inferred_label": clean(row.get("inferred_label"), 300),
            "image_count_on_page": row.get("image_count_on_page"),
            "text_excerpt": clean(row.get("text_excerpt"), 3900),
            "slope_codes": clean(row.get("slope_codes"), 1900),
            "monitor_points": clean(row.get("monitor_points"), 1900),
        })


def insert_questions(conn, rows):
    sql = text("""
        INSERT INTO ai_report_question_sample (
          question_id, question, expected_source, county, report_year, report_month,
          query_type, expected_asset_type, test_status, test_result
        ) VALUES (
          :question_id, :question, :expected_source, :county, :report_year, :report_month,
          :query_type, :expected_asset_type, :test_status, :test_result
        )
    """)
    for row in rows:
        conn.execute(sql, {
            "question_id": clean(row.get("question_id"), 80),
            "question": clean(row.get("question"), 1000),
            "expected_source": clean(row.get("expected_source"), 500),
            "county": clean(row.get("county"), 100),
            "report_year": row.get("report_year"),
            "report_month": row.get("report_month"),
            "query_type": clean(row.get("query_type"), 100),
            "expected_asset_type": clean(row.get("expected_asset_type"), 100),
            "test_status": clean(row.get("test_status"), 50),
            "test_result": clean(row.get("test_result"), 3900),
        })


def main() -> int:
    docs = load_json(SAMPLE_DIR / "report_doc_index.json")
    pages = load_jsonl(SAMPLE_DIR / "report_page_index.jsonl")
    assets = load_jsonl(SAMPLE_DIR / "report_asset_index.jsonl")
    questions = load_json(SAMPLE_DIR / "report_generated_questions.json")

    engine = dm_engine()
    try:
        with engine.begin() as conn:
            create_tables(conn)
            clear_tables(conn)
            insert_docs(conn, docs)
            insert_pages(conn, pages)
            insert_assets(conn, assets)
            insert_questions(conn, questions)
            counts = {
                "ai_report_doc_sample": conn.execute(text("SELECT COUNT(*) FROM ai_report_doc_sample")).scalar(),
                "ai_report_page_sample": conn.execute(text("SELECT COUNT(*) FROM ai_report_page_sample")).scalar(),
                "ai_report_asset_sample": conn.execute(text("SELECT COUNT(*) FROM ai_report_asset_sample")).scalar(),
                "ai_report_question_sample": conn.execute(text("SELECT COUNT(*) FROM ai_report_question_sample")).scalar(),
            }
    finally:
        engine.dispose()
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
