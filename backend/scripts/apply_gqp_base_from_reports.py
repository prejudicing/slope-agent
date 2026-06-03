from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

BACKEND_DIR = Path(__file__).resolve().parents[1]
BUNDLED_SITE_PACKAGES = Path(
    r"C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages"
)
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if BUNDLED_SITE_PACKAGES.exists() and str(BUNDLED_SITE_PACKAGES) not in sys.path:
    sys.path.append(str(BUNDLED_SITE_PACKAGES))

from sqlalchemy import create_engine, text  # noqa: E402

from app.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER  # noqa: E402


def engine():
    password = quote_plus(DM_PASSWORD)
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def norm(value) -> str:
    return str(value or "").strip()


def ensure_log_table(conn) -> None:
    try:
        conn.execute(text("""
CREATE TABLE ai_gqp_base_report_apply_log (
  action_type VARCHAR(50),
  gqpbh VARCHAR(120),
  old_name VARCHAR(500),
  new_name VARCHAR(500),
  old_county VARCHAR(50),
  new_county VARCHAR(50),
  old_professional VARCHAR(50),
  new_professional VARCHAR(50),
  report_year INT,
  report_month INT,
  file_name VARCHAR(500),
  backup_table VARCHAR(120),
  applied_at VARCHAR(30)
)
"""))
    except Exception:
        pass


def load_catalog(conn) -> list[dict]:
    rows = conn.execute(text("""
SELECT county, gqpbh, report_name, is_professional_monitor, monitor_points,
       report_year, report_month, file_name
FROM ai_gqp_report_slope_catalog
WHERE gqpbh IS NOT NULL
  AND gqpbh <> ''
  AND report_name IS NOT NULL
  AND report_name <> ''
ORDER BY county, gqpbh
""")).mappings().all()
    result: dict[str, dict] = {}
    for row in rows:
        code = norm(row.get("gqpbh"))
        name = norm(row.get("report_name"))
        if not code or not name:
            continue
        current = result.get(code)
        score = (
            1 if norm(row.get("is_professional_monitor")) == "是" else 0,
            int(row.get("report_year") or 0),
            int(row.get("report_month") or 0),
            1 if "高切坡" in name else 0,
        )
        if not current or score > current["_score"]:
            result[code] = {key: row.get(key) for key in row.keys()} | {"_score": score}
    return list(result.values())


def apply_from_catalog(dry_run: bool = False) -> dict:
    db = engine()
    applied_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    backup_table = f"geo_gqp_jbxx_bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    summary = {
        "backup_table": backup_table,
        "updated_existing": 0,
        "inserted_missing": 0,
        "marked_professional": 0,
        "dry_run": dry_run,
    }
    try:
        with db.begin() as conn:
            ensure_log_table(conn)
            catalog = load_catalog(conn)
            if not dry_run:
                conn.execute(text(f"CREATE TABLE {backup_table} AS SELECT * FROM geo_gqp_jbxx"))
            max_id = conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM geo_gqp_jbxx")).scalar() or 0
            next_id = int(max_id) + 1
            for item in catalog:
                code = norm(item.get("gqpbh"))
                report_name = norm(item.get("report_name"))
                county = norm(item.get("county"))
                is_professional = norm(item.get("is_professional_monitor")) == "是"
                existing = conn.execute(text("""
SELECT gqpbh, gqpmc, ssqx, sfzyjc, zyjc
FROM geo_gqp_jbxx
WHERE gqpbh = :gqpbh
FETCH FIRST 1 ROWS ONLY
"""), {"gqpbh": code}).mappings().first()
                if existing:
                    old_name = norm(existing.get("gqpmc"))
                    old_county = norm(existing.get("ssqx"))
                    old_professional = norm(existing.get("sfzyjc")) or norm(existing.get("zyjc"))
                    needs_name = old_name != report_name
                    needs_county = county and old_county != county
                    needs_professional = is_professional and old_professional not in {"是", "1", "true", "TRUE", "专业监测", "有"}
                    if not (needs_name or needs_county or needs_professional):
                        continue
                    summary["updated_existing"] += 1
                    if needs_professional:
                        summary["marked_professional"] += 1
                    if not dry_run:
                        conn.execute(text("""
UPDATE geo_gqp_jbxx
SET gqpmc = :gqpmc,
    ssqx = :ssqx,
    sfzyjc = CASE WHEN :is_professional = 1 THEN '是' ELSE sfzyjc END,
    zyjc = CASE WHEN :is_professional = 1 THEN '是' ELSE zyjc END
WHERE gqpbh = :gqpbh
"""), {
                            "gqpmc": report_name,
                            "ssqx": county or old_county,
                            "is_professional": 1 if is_professional else 0,
                            "gqpbh": code,
                        })
                        conn.execute(text("""
INSERT INTO ai_gqp_base_report_apply_log (
  action_type, gqpbh, old_name, new_name, old_county, new_county,
  old_professional, new_professional, report_year, report_month, file_name,
  backup_table, applied_at
) VALUES (
  '更新', :gqpbh, :old_name, :new_name, :old_county, :new_county,
  :old_professional, :new_professional, :report_year, :report_month, :file_name,
  :backup_table, :applied_at
)
"""), {
                            "gqpbh": code,
                            "old_name": old_name,
                            "new_name": report_name,
                            "old_county": old_county,
                            "new_county": county or old_county,
                            "old_professional": old_professional,
                            "new_professional": "是" if is_professional else old_professional,
                            "report_year": item.get("report_year"),
                            "report_month": item.get("report_month"),
                            "file_name": item.get("file_name"),
                            "backup_table": backup_table,
                            "applied_at": applied_at,
                        })
                    continue

                summary["inserted_missing"] += 1
                if is_professional:
                    summary["marked_professional"] += 1
                if not dry_run:
                    conn.execute(text("""
INSERT INTO geo_gqp_jbxx (
  id, gqpbh, gqpmc, ssqx, sfzyjc, zyjc, delete_flag, is_stop, sjly, tb_time, sjtbsj
) VALUES (
  :id, :gqpbh, :gqpmc, :ssqx, :sfzyjc, :zyjc, '0', '0', '月报校核', :applied_at, :applied_at
)
"""), {
                        "id": next_id,
                        "gqpbh": code,
                        "gqpmc": report_name,
                        "ssqx": county,
                        "sfzyjc": "是" if is_professional else None,
                        "zyjc": "是" if is_professional else None,
                        "applied_at": applied_at,
                    })
                    next_id += 1
                    conn.execute(text("""
INSERT INTO ai_gqp_base_report_apply_log (
  action_type, gqpbh, old_name, new_name, old_county, new_county,
  old_professional, new_professional, report_year, report_month, file_name,
  backup_table, applied_at
) VALUES (
  '新增', :gqpbh, '', :new_name, '', :new_county,
  '', :new_professional, :report_year, :report_month, :file_name,
  :backup_table, :applied_at
)
"""), {
                        "gqpbh": code,
                        "new_name": report_name,
                        "new_county": county,
                        "new_professional": "是" if is_professional else "",
                        "report_year": item.get("report_year"),
                        "report_month": item.get("report_month"),
                        "file_name": item.get("file_name"),
                        "backup_table": backup_table,
                        "applied_at": applied_at,
                    })
    finally:
        db.dispose()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写入")
    args = parser.parse_args()
    print(json.dumps(apply_from_catalog(dry_run=args.dry_run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
