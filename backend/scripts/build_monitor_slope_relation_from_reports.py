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


OUT_DIR = BACKEND_DIR / "generated" / "monitor_slope_relation"
TARGET_COUNTIES = {"兴山县", "夷陵区", "巴东县", "秭归县"}
SLOPE_CODE_RE = re.compile(r"\b(?:XS|EXS|YL|EYL|BD|EBD|ZG|EZG|420)\d+[A-Z0-9*\-]*\b", re.IGNORECASE)
POINT_RE = re.compile(r"\b(?:XSTJC|BDJC|BDGPSJC|BDTPSJC|ZXJC|ZXTJC|[A-Z]{0,4}JC|JZ|KZ)\d+[A-Z0-9\-]*\b", re.IGNORECASE)
DISPLACEMENT_ROW_RE = re.compile(
    r"\b((?:XSTJC|BDJC|BDGPSJC|BDTPSJC|ZXJC|ZXTJC|[A-Z]{0,4}JC|JZ|KZ)\d+[A-Z0-9\-]*)\b\s+"
    r"(\d{6}|\d{4}[.-]?\d{1,2})\s+"
    r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+"
    r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+"
    r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
POINT_RANGE_RE = re.compile(r"\b((?:XSTJC|BDJC|BDGPSJC|BDTPSJC|ZXJC|ZXTJC|[A-Z]{0,4}JC|JZ|KZ))(\d+)\s*[~～-]\s*(?:\1)?(\d+)\b", re.IGNORECASE)


@dataclass
class RelationRow:
    county: str
    gqpbh: str
    gqpmc: str
    monitor_point: str
    source_type: str
    report_year: int | None
    report_month: int | None
    file_hash: str
    file_name: str
    evidence: str
    confidence: str
    created_at: str
    current_x: float | None = None
    cumulative_x: float | None = None
    current_y: float | None = None
    cumulative_y: float | None = None
    current_h: float | None = None
    cumulative_h: float | None = None


def engine():
    password = quote_plus(DM_PASSWORD)
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def norm(value) -> str:
    return str(value or "").strip()


def clean_name(value: str) -> str:
    name = norm(value)
    name = re.sub(r"^[（(]?\d+[）)、.．\s]+", "", name)
    name = re.sub(r"^\d+(?:\.\d+)?\s*(?:m{1,2}|cm)\s*[（(]?", "", name, flags=re.IGNORECASE)
    name = name.strip(" ，,。；;：:（）()[]【】")
    if "高切坡" in name:
        match = re.search(r"([\u4e00-\u9fa5A-Za-z0-9#、\-—（）()]{2,45}?高切坡)", name)
        if match:
            name = match.group(1).strip(" ，,。；;：:（）()[]【】")
    elif name.endswith("高切"):
        name = f"{name}坡"
    return name


def load_slope_catalog(conn) -> dict[str, dict]:
    rows = conn.execute(text("""
SELECT county, gqpbh, report_name
FROM ai_gqp_report_slope_catalog
WHERE gqpbh IS NOT NULL AND gqpbh <> ''
""")).mappings().all()
    catalog: dict[str, dict] = {}
    for row in rows:
        code = norm(row.get("gqpbh")).upper()
        if not code:
            continue
        name = clean_name(row.get("report_name"))
        catalog[code] = {
            "county": norm(row.get("county")),
            "gqpbh": norm(row.get("gqpbh")),
            "gqpmc": name,
        }
    base_rows = conn.execute(text("""
SELECT ssqx, gqpbh, gqpmc
FROM geo_gqp_jbxx
WHERE gqpbh IS NOT NULL AND gqpbh <> ''
""")).mappings().all()
    for row in base_rows:
        code = norm(row.get("gqpbh")).upper()
        if code and code not in catalog:
            catalog[code] = {
                "county": norm(row.get("ssqx")),
                "gqpbh": norm(row.get("gqpbh")),
                "gqpmc": clean_name(row.get("gqpmc")),
            }
    return catalog


def load_chunks(conn) -> list[dict]:
    rows = conn.execute(text("""
SELECT c.county, c.report_year, c.report_month, c.file_hash, c.chunk_index, c.content,
       d.file_name
FROM ai_monthly_report_chunk c
LEFT JOIN ai_monthly_report_doc d ON d.file_hash = c.file_hash
WHERE c.county IN ('兴山县','夷陵区','巴东县','秭归县')
  AND c.content IS NOT NULL
ORDER BY c.county, c.report_year DESC NULLS LAST, c.report_month DESC NULLS LAST, c.chunk_index
""")).mappings().all()
    return [{key: row.get(key) for key in row.keys()} for row in rows]


def expand_point_ranges(text_value: str) -> list[str]:
    points: list[str] = []
    for match in POINT_RANGE_RE.finditer(text_value):
        prefix = match.group(1)
        start = int(match.group(2))
        end = int(match.group(3))
        width = max(len(match.group(2)), len(match.group(3)))
        if 0 <= end - start <= 80:
            points.extend(f"{prefix}{num:0{width}d}" for num in range(start, end + 1))
    return points


def extract_points(text_value: str) -> list[str]:
    values = expand_point_ranges(text_value)
    values.extend(POINT_RE.findall(text_value))
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        point = norm(value).upper()
        if not point or point in seen:
            continue
        seen.add(point)
        result.append(point)
    return result


def infer_name_near_code(content: str, code: str) -> str:
    escaped = re.escape(code)
    patterns = [
        rf"([\u4e00-\u9fa5A-Za-z0-9#、\-—（）()]{{2,45}}?高切坡)\s*[（(]\s*{escaped}\s*[）)]",
        rf"{escaped}\s*([\u4e00-\u9fa5A-Za-z0-9#、\-—（）()]{{2,45}}?高切坡)",
    ]
    for pattern in patterns:
        match = re.search(pattern, content, flags=re.IGNORECASE)
        if match:
            name = clean_name(match.group(1))
            if name:
                return name
    return ""


def window_around(content: str, index: int, left: int = 260, right: int = 360) -> str:
    return content[max(0, index - left): min(len(content), index + right)]


def rows_from_displacement_tables(chunk: dict, catalog: dict[str, dict], lines: list[str], created_at: str) -> list[RelationRow]:
    rows: list[RelationRow] = []
    county = norm(chunk.get("county"))
    active_code = ""
    active_name = ""
    recent_names: list[str] = []
    recent_codes: list[str] = []
    for line in lines:
        codes = [match.group(0) for match in SLOPE_CODE_RE.finditer(line)]
        if codes:
            active_code = codes[-1]
            catalog_item = catalog.get(active_code.upper(), {})
            active_name = catalog_item.get("gqpmc") or infer_name_near_code(line, active_code) or active_name
            recent_codes.append(active_code)
            recent_codes = recent_codes[-3:]
        if "高切坡" in line and not DISPLACEMENT_ROW_RE.search(line):
            cleaned = clean_name(line)
            if cleaned:
                recent_names.append(cleaned)
                recent_names = recent_names[-3:]
                if not active_name:
                    active_name = cleaned
        match = DISPLACEMENT_ROW_RE.search(line)
        if not match:
            continue
        code = active_code or (recent_codes[-1] if recent_codes else "")
        if not code:
            continue
        code_key = code.upper()
        catalog_item = catalog.get(code_key, {})
        name = catalog_item.get("gqpmc") or active_name or (recent_names[-1] if recent_names else "") or code
        values = [float(match.group(idx)) for idx in range(3, 9)]
        rows.append(RelationRow(
            county=county,
            gqpbh=catalog_item.get("gqpbh") or code,
            gqpmc=name,
            monitor_point=match.group(1).upper(),
            source_type="月报监测成果表",
            report_year=chunk.get("report_year"),
            report_month=chunk.get("report_month"),
            file_hash=norm(chunk.get("file_hash")),
            file_name=norm(chunk.get("file_name")),
            evidence=line[:900],
            confidence="高",
            created_at=created_at,
            current_x=values[0],
            cumulative_x=values[1],
            current_y=values[2],
            cumulative_y=values[3],
            current_h=values[4],
            cumulative_h=values[5],
        ))
    return rows


def rows_from_chunks(chunks: list[dict], catalog: dict[str, dict]) -> list[RelationRow]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[RelationRow] = []
    for chunk in chunks:
        county = norm(chunk.get("county"))
        if county not in TARGET_COUNTIES:
            continue
        content = norm(chunk.get("content"))
        if not content or not ("监测" in content and "高切坡" in content):
            continue
        lines = [line.strip() for line in re.split(r"[\r\n]+", content) if line.strip()]
        rows.extend(rows_from_displacement_tables(chunk, catalog, lines, now))
        for idx, line in enumerate(lines):
            codes = [match.group(0) for match in SLOPE_CODE_RE.finditer(line)]
            if not codes:
                continue
            local_text = line
            if not extract_points(local_text):
                nearby = " ".join(lines[idx:min(len(lines), idx + 3)])
                if any(flag in nearby for flag in ("监测点号", "点号", "监测点")):
                    local_text = nearby
            points = extract_points(local_text)
            if not points:
                continue
            if len(codes) > 1 and len(points) > 8:
                continue
            for code in codes:
                code_key = code.upper()
                catalog_item = catalog.get(code_key, {})
                name = catalog_item.get("gqpmc") or infer_name_near_code(local_text, code) or code
                for point in points:
                    if point.upper() == code_key:
                        continue
                    rows.append(RelationRow(
                        county=county,
                        gqpbh=catalog_item.get("gqpbh") or code,
                        gqpmc=name,
                        monitor_point=point,
                        source_type="月报表格/正文",
                        report_year=chunk.get("report_year"),
                        report_month=chunk.get("report_month"),
                        file_hash=norm(chunk.get("file_hash")),
                        file_name=norm(chunk.get("file_name")),
                        evidence=local_text[:900],
                        confidence="高" if ("点号" in local_text or "监测点" in local_text) else "中",
                        created_at=now,
                    ))
    return rows


def rows_from_existing_curve_map(conn) -> list[RelationRow]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(text("""
SELECT county, report_year, report_month, file_hash, file_name, gqpbh, gqpmc, monitor_point, chart_title
FROM ai_professional_monitor_point_map
WHERE gqpbh IS NOT NULL AND gqpbh <> ''
  AND monitor_point IS NOT NULL AND monitor_point <> ''
  AND gqpbh NOT LIKE '第%'
  AND monitor_point NOT LIKE 'P%'
""")).mappings().all()
    result: list[RelationRow] = []
    for row in rows:
        result.append(RelationRow(
            county=norm(row.get("county")),
            gqpbh=norm(row.get("gqpbh")),
            gqpmc=clean_name(row.get("gqpmc")) or norm(row.get("gqpbh")),
            monitor_point=norm(row.get("monitor_point")).upper(),
            source_type="月报曲线/表格登记",
            report_year=row.get("report_year"),
            report_month=row.get("report_month"),
            file_hash=norm(row.get("file_hash")),
            file_name=norm(row.get("file_name")),
            evidence=norm(row.get("chart_title")),
            confidence="高",
            created_at=now,
        ))
    return result


def dedupe_rows(rows: list[RelationRow]) -> list[RelationRow]:
    by_key: dict[tuple[str, str, str], RelationRow] = {}
    rank = {"高": 2, "中": 1, "低": 0}
    for row in rows:
        if not row.gqpbh or not row.monitor_point:
            continue
        key = (row.county, row.gqpbh.upper(), row.monitor_point.upper())
        old = by_key.get(key)
        if not old:
            by_key[key] = row
            continue
        old_has_values = 1 if old.cumulative_x is not None or old.cumulative_y is not None or old.cumulative_h is not None else 0
        new_has_values = 1 if row.cumulative_x is not None or row.cumulative_y is not None or row.cumulative_h is not None else 0
        old_score = (old_has_values, rank.get(old.confidence, 0), old.report_year or 0, old.report_month or 0, len(old.evidence))
        new_score = (new_has_values, rank.get(row.confidence, 0), row.report_year or 0, row.report_month or 0, len(row.evidence))
        if new_score > old_score:
            by_key[key] = row
    return sorted(by_key.values(), key=lambda item: (item.county, item.gqpbh, item.monitor_point))


def sync_to_dm(rows: list[RelationRow]) -> None:
    db = engine()
    try:
        with db.begin() as conn:
            try:
                conn.execute(text("""
CREATE TABLE ai_report_monitor_slope_map (
  county VARCHAR(50),
  gqpbh VARCHAR(120),
  gqpmc VARCHAR(500),
  monitor_point VARCHAR(120),
  source_type VARCHAR(80),
  report_year INT,
  report_month INT,
  file_hash VARCHAR(128),
  file_name VARCHAR(500),
  evidence CLOB,
  confidence VARCHAR(20),
  created_at VARCHAR(30),
  current_x DECIMAL(18,2),
  cumulative_x DECIMAL(18,2),
  current_y DECIMAL(18,2),
  cumulative_y DECIMAL(18,2),
  current_h DECIMAL(18,2),
  cumulative_h DECIMAL(18,2)
)
"""))
            except Exception:
                pass
            existing_columns = {
                str(row[0]).lower()
                for row in conn.execute(text("SELECT column_name FROM user_tab_columns WHERE table_name = UPPER('ai_report_monitor_slope_map')")).fetchall()
            }
            for column_name in ("current_x", "cumulative_x", "current_y", "cumulative_y", "current_h", "cumulative_h"):
                if column_name not in existing_columns:
                    try:
                        conn.execute(text(f"ALTER TABLE ai_report_monitor_slope_map ADD {column_name} DECIMAL(18,2)"))
                    except Exception:
                        pass
            conn.execute(text("DELETE FROM ai_report_monitor_slope_map"))
            insert_sql = text("""
INSERT INTO ai_report_monitor_slope_map (
  county, gqpbh, gqpmc, monitor_point, source_type, report_year, report_month,
  file_hash, file_name, evidence, confidence, created_at,
  current_x, cumulative_x, current_y, cumulative_y, current_h, cumulative_h
) VALUES (
  :county, :gqpbh, :gqpmc, :monitor_point, :source_type, :report_year, :report_month,
  :file_hash, :file_name, :evidence, :confidence, :created_at,
  :current_x, :cumulative_x, :current_y, :cumulative_y, :current_h, :cumulative_h
)
""")
            for row in rows:
                conn.execute(insert_sql, asdict(row))
    finally:
        db.dispose()


def write_outputs(rows: list[RelationRow], summary: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "monitor_slope_relation.json"
    path.write_text(json.dumps({"summary": summary, "rows": [asdict(row) for row in rows]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync-db", action="store_true")
    args = parser.parse_args()

    db = engine()
    try:
        with db.connect() as conn:
            catalog = load_slope_catalog(conn)
            chunks = load_chunks(conn)
            rows = rows_from_existing_curve_map(conn)
            rows.extend(rows_from_chunks(chunks, catalog))
    finally:
        db.dispose()

    rows = dedupe_rows(rows)
    county_counts = defaultdict(int)
    slope_counts = defaultdict(set)
    for row in rows:
        county_counts[row.county] += 1
        slope_counts[row.county].add(row.gqpbh.upper())
    summary = {
        "row_count": len(rows),
        "point_count_by_county": dict(sorted(county_counts.items())),
        "slope_count_by_county": {key: len(value) for key, value in sorted(slope_counts.items())},
    }
    path = write_outputs(rows, summary)
    if args.sync_db:
        sync_to_dm(rows)
    print(json.dumps({**summary, "json": str(path), "synced_db": bool(args.sync_db)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
