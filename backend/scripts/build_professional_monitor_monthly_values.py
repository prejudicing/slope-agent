from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
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
from scripts.build_monitor_slope_relation_from_reports import (  # noqa: E402
    SLOPE_CODE_RE,
    clean_name,
    infer_name_near_code,
    load_slope_catalog,
    norm,
)


OUT_DIR = BACKEND_DIR / "generated" / "professional_monitor_monthly_values"
TARGET_COUNTIES = {"兴山县", "夷陵区", "巴东县", "秭归县"}
POINT_RE_PART = r"(?:XSTJC|BDJC|BDGPSJC|BDTPSJC|ZXJC|ZXTJC|[A-Z]{0,4}JC|JZ|KZ)"
DISPLACEMENT_ROW_RE = re.compile(
    rf"\b(({POINT_RE_PART})\d+[A-Z0-9\-]*)\b\s+"
    r"(\d{6}|\d{4}[.-]?\d{1,2})\s+"
    r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+"
    r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+"
    r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
VERTICAL_POINT_RE = re.compile(r"^(BDJC\d+[A-Z0-9\-]*)$", re.IGNORECASE)
NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


@dataclass
class MonthlyValueRow:
    county: str
    gqpbh: str
    gqpmc: str
    monitor_point: str
    report_year: int
    report_month: int
    first_observe_month: str
    current_x: float
    cumulative_x: float
    current_y: float
    cumulative_y: float
    current_h: float
    cumulative_h: float
    file_hash: str
    file_name: str
    evidence: str
    confidence: str
    created_at: str


def engine():
    password = quote_plus(DM_PASSWORD)
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def load_report_chunks(conn) -> list[dict]:
    rows = conn.execute(text("""
SELECT
  c.county,
  c.report_year,
  c.report_month,
  c.file_hash,
  c.chunk_index,
  c.content,
  d.file_name,
  d.report_type
FROM ai_monthly_report_chunk c
LEFT JOIN ai_monthly_report_doc d ON d.file_hash = c.file_hash
WHERE c.county IN ('兴山县','夷陵区','巴东县','秭归县')
  AND c.report_year = 2025
  AND c.report_month IS NOT NULL
  AND c.content IS NOT NULL
ORDER BY c.county, c.report_month, c.file_hash, c.chunk_index
""")).mappings().all()
    return [{key: row.get(key) for key in row.keys()} for row in rows]


def update_active_slope(line: str, catalog: dict[str, dict], active_code: str, active_name: str) -> tuple[str, str]:
    codes = [match.group(0) for match in SLOPE_CODE_RE.finditer(line)]
    if codes:
        code = codes[-1]
        if line.strip().upper() == code.upper() and re.match(r"^(?:BD\d{3}|JZ\d+)$", code, re.IGNORECASE):
            return active_code, active_name
        catalog_item = catalog.get(code.upper(), {})
        name = catalog_item.get("gqpmc") or infer_name_near_code(line, code) or active_name
        return catalog_item.get("gqpbh") or code, clean_name(name) or active_name
    if "高切坡" in line and not DISPLACEMENT_ROW_RE.search(line):
        name = clean_name(line)
        if name:
            return active_code, name
    return active_code, active_name


def rows_from_file(chunks: list[dict], catalog: dict[str, dict], created_at: str) -> list[MonthlyValueRow]:
    rows: list[MonthlyValueRow] = []
    active_code = ""
    active_name = ""
    vertical_point = ""
    vertical_values: list[float] = []
    vertical_evidence: list[str] = []
    chunks = sorted(chunks, key=lambda item: int(item.get("chunk_index") or 0))

    def flush_vertical(chunk: dict) -> None:
        nonlocal vertical_point, vertical_values, vertical_evidence
        if active_code and vertical_point and len(vertical_values) >= 3:
            code_key = active_code.upper()
            catalog_item = catalog.get(code_key, {})
            gqpbh = catalog_item.get("gqpbh") or active_code
            gqpmc = catalog_item.get("gqpmc") or active_name or gqpbh
            rows.append(MonthlyValueRow(
                county=norm(chunk.get("county")),
                gqpbh=gqpbh,
                gqpmc=clean_name(gqpmc) or gqpbh,
                monitor_point=vertical_point.upper(),
                report_year=int(chunk.get("report_year") or 0),
                report_month=int(chunk.get("report_month") or 0),
                first_observe_month="",
                current_x=vertical_values[0],
                cumulative_x=vertical_values[0],
                current_y=vertical_values[1],
                cumulative_y=vertical_values[1],
                current_h=vertical_values[2],
                cumulative_h=vertical_values[2],
                file_hash=norm(chunk.get("file_hash")),
                file_name=norm(chunk.get("file_name")),
                evidence=" ".join(vertical_evidence)[:900],
                confidence="中",
                created_at=created_at,
            ))
        vertical_point = ""
        vertical_values = []
        vertical_evidence = []

    for chunk in chunks:
        county = norm(chunk.get("county"))
        if county not in TARGET_COUNTIES:
            continue
        content = norm(chunk.get("content"))
        if not content:
            continue
        for raw_line in re.split(r"[\r\n]+", content):
            line = raw_line.strip()
            if not line:
                continue
            point_match = VERTICAL_POINT_RE.match(line)
            if point_match:
                flush_vertical(chunk)
                vertical_point = point_match.group(1).upper()
                vertical_values = []
                vertical_evidence = [line]
                continue
            if vertical_point and NUMBER_RE.match(line):
                vertical_values.append(float(line))
                vertical_evidence.append(line)
                if len(vertical_values) >= 3:
                    flush_vertical(chunk)
                continue
            elif vertical_point:
                flush_vertical(chunk)
            active_code, active_name = update_active_slope(line, catalog, active_code, active_name)
            match = DISPLACEMENT_ROW_RE.search(line)
            if not match or not active_code:
                continue
            code_key = active_code.upper()
            catalog_item = catalog.get(code_key, {})
            gqpbh = catalog_item.get("gqpbh") or active_code
            gqpmc = catalog_item.get("gqpmc") or active_name or gqpbh
            values = [float(match.group(idx)) for idx in range(4, 10)]
            rows.append(MonthlyValueRow(
                county=county,
                gqpbh=gqpbh,
                gqpmc=clean_name(gqpmc) or gqpbh,
                monitor_point=match.group(1).upper(),
                report_year=int(chunk.get("report_year") or 0),
                report_month=int(chunk.get("report_month") or 0),
                first_observe_month=match.group(3),
                current_x=values[0],
                cumulative_x=values[1],
                current_y=values[2],
                cumulative_y=values[3],
                current_h=values[4],
                cumulative_h=values[5],
                file_hash=norm(chunk.get("file_hash")),
                file_name=norm(chunk.get("file_name")),
                evidence=line[:900],
                confidence="高",
                created_at=created_at,
            ))
        if vertical_point:
            flush_vertical(chunk)
    return rows


def dedupe_rows(rows: list[MonthlyValueRow]) -> list[MonthlyValueRow]:
    by_key: dict[tuple[str, str, str, int, int], MonthlyValueRow] = {}
    for row in rows:
        if not row.gqpbh or not row.monitor_point or row.monitor_point.startswith("KZ"):
            continue
        key = (
            row.county,
            row.gqpbh.upper(),
            row.monitor_point.upper(),
            int(row.report_year),
            int(row.report_month),
        )
        old = by_key.get(key)
        if not old:
            by_key[key] = row
            continue
        old_score = (len(old.gqpmc), "盖章" not in old.file_name, len(old.evidence))
        new_score = (len(row.gqpmc), "盖章" not in row.file_name, len(row.evidence))
        if new_score > old_score:
            by_key[key] = row
    return sorted(by_key.values(), key=lambda item: (item.county, item.gqpbh, item.monitor_point, item.report_year, item.report_month))


def sync_to_dm(rows: list[MonthlyValueRow]) -> None:
    db = engine()
    try:
        with db.begin() as conn:
            try:
                conn.execute(text("""
CREATE TABLE ai_professional_monitor_monthly_value (
  county VARCHAR(50),
  gqpbh VARCHAR(120),
  gqpmc VARCHAR(500),
  monitor_point VARCHAR(120),
  report_year INT,
  report_month INT,
  first_observe_month VARCHAR(20),
  current_x DECIMAL(18,2),
  cumulative_x DECIMAL(18,2),
  current_y DECIMAL(18,2),
  cumulative_y DECIMAL(18,2),
  current_h DECIMAL(18,2),
  cumulative_h DECIMAL(18,2),
  file_hash VARCHAR(128),
  file_name VARCHAR(500),
  evidence CLOB,
  confidence VARCHAR(20),
  created_at VARCHAR(30)
)
"""))
            except Exception:
                pass
            conn.execute(text("DELETE FROM ai_professional_monitor_monthly_value"))
            insert_sql = text("""
INSERT INTO ai_professional_monitor_monthly_value (
  county, gqpbh, gqpmc, monitor_point, report_year, report_month, first_observe_month,
  current_x, cumulative_x, current_y, cumulative_y, current_h, cumulative_h,
  file_hash, file_name, evidence, confidence, created_at
) VALUES (
  :county, :gqpbh, :gqpmc, :monitor_point, :report_year, :report_month, :first_observe_month,
  :current_x, :cumulative_x, :current_y, :cumulative_y, :current_h, :cumulative_h,
  :file_hash, :file_name, :evidence, :confidence, :created_at
)
""")
            for row in rows:
                conn.execute(insert_sql, asdict(row))
    finally:
        db.dispose()


def write_outputs(rows: list[MonthlyValueRow], summary: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "monthly_values.json"
    path.write_text(json.dumps({"summary": summary, "rows": [asdict(row) for row in rows]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_summary(rows: list[MonthlyValueRow]) -> dict:
    county_points: dict[str, set[str]] = defaultdict(set)
    county_slopes: dict[str, set[str]] = defaultdict(set)
    county_months: dict[str, set[int]] = defaultdict(set)
    point_months: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    for row in rows:
        county_points[row.county].add(f"{row.gqpbh.upper()}::{row.monitor_point.upper()}")
        county_slopes[row.county].add(row.gqpbh.upper())
        county_months[row.county].add(row.report_month)
        point_months[(row.county, row.gqpbh.upper(), row.monitor_point.upper())].add(row.report_month)
    continuity = {
        "point_with_1_month": sum(1 for months in point_months.values() if len(months) == 1),
        "point_with_2_to_5_months": sum(1 for months in point_months.values() if 2 <= len(months) <= 5),
        "point_with_6_plus_months": sum(1 for months in point_months.values() if len(months) >= 6),
    }
    return {
        "row_count": len(rows),
        "slope_count_by_county": {key: len(value) for key, value in sorted(county_slopes.items())},
        "point_count_by_county": {key: len(value) for key, value in sorted(county_points.items())},
        "month_count_by_county": {key: len(value) for key, value in sorted(county_months.items())},
        "continuity": continuity,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync-db", action="store_true")
    args = parser.parse_args()

    db = engine()
    try:
        with db.connect() as conn:
            catalog = load_slope_catalog(conn)
            chunks = load_report_chunks(conn)
    finally:
        db.dispose()

    grouped: dict[str, list[dict]] = defaultdict(list)
    for chunk in chunks:
        grouped[norm(chunk.get("file_hash"))].append(chunk)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[MonthlyValueRow] = []
    for file_chunks in grouped.values():
        rows.extend(rows_from_file(file_chunks, catalog, now))
    rows = dedupe_rows(rows)
    summary = build_summary(rows)
    path = write_outputs(rows, summary)
    if args.sync_db:
        sync_to_dm(rows)
    print(json.dumps({**summary, "json": str(path), "synced_db": bool(args.sync_db)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
