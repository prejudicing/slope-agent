from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
BUNDLED_SITE_PACKAGES = Path(
    r"C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages"
)
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if BUNDLED_SITE_PACKAGES.exists() and str(BUNDLED_SITE_PACKAGES) not in sys.path:
    sys.path.append(str(BUNDLED_SITE_PACKAGES))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER  # noqa: E402
from app.dashboards.displacement_dashboard import _resolve_display_name  # noqa: E402


OUT_DIR = BACKEND_DIR / "generated" / "gqp_base_audit"
TARGET_COUNTIES = ("兴山县", "夷陵区", "巴东县", "秭归县")
VALID_CODE_RE = re.compile(r"^(?!第)[A-Z]{1,5}\d+[A-Z0-9*\-]*$")
YES_VALUES = {"1", "是", "true", "TRUE", "专业监测", "有", "Y", "y"}
CODE_RE = re.compile(r"\b[A-Z]{1,5}\d+[A-Z0-9*\-]*\b")
GQP_CODE_PREFIXES = ("XS", "EXS", "YL", "EYL", "BD", "EBD", "ZG", "EZG", "420")


@dataclass
class AuditRow:
    county: str
    gqpbh: str
    base_name: str
    report_name: str
    issue_type: str
    suggested_action: str
    monitor_points: str
    report_year: int | None
    report_month: int | None
    file_name: str
    evidence: str
    confidence: str
    created_at: str


def engine():
    password = quote_plus(DM_PASSWORD)
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def norm(value) -> str:
    return str(value or "").strip()


def is_yes(value) -> bool:
    return norm(value) in YES_VALUES


def valid_report_code(code: str) -> bool:
    value = norm(code).upper()
    if not VALID_CODE_RE.match(value):
        return False
    return value.startswith(GQP_CODE_PREFIXES)


def normalized_name(name: str) -> str:
    value = norm(name)
    value = re.sub(r"\s+", "", value)
    value = value.replace("（", "(").replace("）", ")")
    return value


def load_base_rows(conn) -> dict[str, dict]:
    rows = conn.execute(text("""
SELECT gqpbh, gqpmc, ssqx, sfzyjc, zyjc, sfqcqf, warned, assessment
FROM geo_gqp_jbxx
""")).mappings().all()
    result: dict[str, dict] = {}
    for row in rows:
        code = norm(row.get("gqpbh"))
        if not code:
            continue
        result[code.upper()] = {key: row.get(key) for key in row.keys()}
    return result


def load_report_rows(conn) -> list[dict]:
    rows = conn.execute(text("""
SELECT county, report_year, report_month, report_type, file_hash, file_name,
       gqpbh, gqpmc, monitor_point, chart_title, latest_monitor_date
FROM ai_professional_monitor_point_map
ORDER BY county, report_year DESC NULLS LAST, report_month DESC NULLS LAST, gqpbh, monitor_point
""")).mappings().all()
    return [{key: row.get(key) for key in row.keys()} for row in rows]


def load_report_chunks(conn) -> list[dict]:
    rows = conn.execute(text("""
SELECT c.county, c.report_year, c.report_month, c.report_type, c.content,
       d.file_name, d.file_hash
FROM ai_monthly_report_chunk c
LEFT JOIN ai_monthly_report_doc d ON d.file_hash = c.file_hash
WHERE c.county IS NOT NULL
  AND c.county <> ''
ORDER BY c.county, c.report_year DESC NULLS LAST, c.report_month DESC NULLS LAST, c.chunk_index
""")).mappings().all()
    return [{key: row.get(key) for key in row.keys()} for row in rows]


def best_report_name(row: dict) -> str:
    county = norm(row.get("county"))
    code = norm(row.get("gqpbh"))
    raw_name = norm(row.get("gqpmc"))
    monitor_point = norm(row.get("monitor_point"))
    title = norm(row.get("chart_title"))
    if not valid_report_code(code):
        return raw_name
    return _resolve_display_name(county, code, raw_name, monitor_point, title)


def group_report_slopes(report_rows: list[dict]) -> dict[str, dict]:
    grouped: dict[str, dict] = {}
    for row in report_rows:
        code = norm(row.get("gqpbh"))
        if not valid_report_code(code):
            continue
        county = norm(row.get("county"))
        if county not in TARGET_COUNTIES:
            continue
        name = best_report_name(row)
        if not name or name == code or name.startswith("第"):
            name = norm(row.get("gqpmc"))
        key = f"{county}::{code}"
        item = grouped.setdefault(key, {
            "county": county,
            "gqpbh": code,
            "names": defaultdict(int),
            "points": set(),
            "report_year": row.get("report_year"),
            "report_month": row.get("report_month"),
            "file_name": norm(row.get("file_name")),
            "evidence": norm(row.get("chart_title")),
        })
        if name:
            item["names"][name] += 1
        point = norm(row.get("monitor_point"))
        if point:
            item["points"].add(point)
        year = row.get("report_year") or 0
        month = row.get("report_month") or 0
        old_year = item["report_year"] or 0
        old_month = item["report_month"] or 0
        if (year, month) > (old_year, old_month):
            item["report_year"] = row.get("report_year")
            item["report_month"] = row.get("report_month")
            item["file_name"] = norm(row.get("file_name"))
            item["evidence"] = norm(row.get("chart_title"))
    return grouped


def clean_report_name(raw_name: str, code: str) -> str:
    name = norm(raw_name)
    name = re.split(r"[\r\n]", name)[-1]
    name = name.replace(code, "")
    name = re.sub(r"^[（(]?\d+[）)、.．\s]+", "", name)
    name = re.sub(r"^\d+(?:\.\d+)?\s*(?:m{1,2}|cm)\s*[（(]?", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^(?:m{1,2}|cm|单位[:：]?)\s*[（(]?", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^(其中|由于|以及|分别为|为|和|与|项目|工程)", "", name)
    name = name.strip(" ，,。；;：:（）()[]【】")
    if "高切坡" in name:
        match = re.search(r"([\u4e00-\u9fa5A-Za-z0-9#、\-—（）()]{2,45}?高切坡)", name)
        if match:
            name = match.group(1).strip(" ，,。；;：:（）()[]【】")
    elif name.endswith("高切"):
        name = f"{name}坡"
    if not name or name == code or len(name) > 60:
        return ""
    bad_words = ("月报", "报告", "目录", "监测点", "位移", "过程线", "工作情况")
    if any(word == name for word in bad_words):
        return ""
    return name


def extract_slope_pairs(content: str) -> list[tuple[str, str]]:
    text_value = norm(content)
    if not text_value:
        return []
    pairs: list[tuple[str, str]] = []
    patterns = [
        r"([\u4e00-\u9fa5A-Za-z0-9#、\-—（）()]{2,45}?高切坡)\s*[（(]\s*([A-Z]{1,5}\d+[A-Z0-9*\-]*)\s*[）)]",
        r"([A-Z]{1,5}\d+[A-Z0-9*\-]*)\s*([\u4e00-\u9fa5A-Za-z0-9#、\-—（）()]{2,45}?高切坡)",
        r"([\u4e00-\u9fa5A-Za-z0-9#、\-—（）()]{2,35}?)\s*[（(]\s*([A-Z]{1,5}\d+[A-Z0-9*\-]*)\s*[）)]",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text_value):
            if match.group(1).startswith(tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")):
                code = match.group(1)
                name = match.group(2)
            else:
                name = match.group(1)
                code = match.group(2)
            if not valid_report_code(code):
                continue
            cleaned = clean_report_name(name, code)
            if cleaned:
                pairs.append((code, cleaned))
    return pairs


def merge_chunk_catalog(report_slopes: dict[str, dict], chunks: list[dict]) -> dict[str, dict]:
    for chunk in chunks:
        county = norm(chunk.get("county"))
        if county not in TARGET_COUNTIES:
            continue
        content = norm(chunk.get("content"))
        is_professional_context = "专业监测" in content or "专业监测" in norm(chunk.get("report_type")) or "专业监测" in norm(chunk.get("file_name"))
        for code, name in extract_slope_pairs(content):
            key = f"{county}::{code}"
            item = report_slopes.setdefault(key, {
                "county": county,
                "gqpbh": code,
                "names": defaultdict(int),
                "points": set(),
                "report_year": chunk.get("report_year"),
                "report_month": chunk.get("report_month"),
                "file_name": norm(chunk.get("file_name")),
                "evidence": "",
                "professional_context": False,
            })
            item["names"][name] += 1
            if is_professional_context:
                item["professional_context"] = True
            year = chunk.get("report_year") or 0
            month = chunk.get("report_month") or 0
            old_year = item["report_year"] or 0
            old_month = item["report_month"] or 0
            if (year, month) >= (old_year, old_month):
                item["report_year"] = chunk.get("report_year")
                item["report_month"] = chunk.get("report_month")
                item["file_name"] = norm(chunk.get("file_name"))
                if not item.get("evidence"):
                    item["evidence"] = content[:500]
    return report_slopes


def build_audit_rows(base_by_code: dict[str, dict], report_slopes: dict[str, dict]) -> list[AuditRow]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    audit_rows: list[AuditRow] = []
    for item in report_slopes.values():
        code = item["gqpbh"]
        county = item["county"]
        report_name = ""
        if item["names"]:
            report_name = sorted(item["names"].items(), key=lambda pair: (-pair[1], len(pair[0])))[0][0]
        base = base_by_code.get(code.upper())
        points = "、".join(sorted(item["points"]))
        common = {
            "county": county,
            "gqpbh": code,
            "report_name": report_name,
            "monitor_points": points,
            "report_year": item["report_year"],
            "report_month": item["report_month"],
            "file_name": item["file_name"],
            "evidence": item["evidence"][:900],
            "created_at": now,
        }
        if not base:
            audit_rows.append(AuditRow(
                **common,
                base_name="",
                issue_type="基础资料缺少该编号",
                suggested_action="建议核实后新增基础资料，或确认月报编号是否为监测项目内部编号。",
                confidence="中",
            ))
            continue
        base_name = norm(base.get("gqpmc"))
        base_county = norm(base.get("ssqx"))
        if report_name and normalized_name(base_name) != normalized_name(report_name):
            audit_rows.append(AuditRow(
                **common,
                base_name=base_name,
                issue_type="名称不一致",
                suggested_action=f"建议核实名称是否应由“{base_name}”调整为“{report_name}”。",
                confidence="高" if "高切坡" in report_name else "中",
            ))
        if county and base_county and county != base_county:
            audit_rows.append(AuditRow(
                **common,
                base_name=base_name,
                issue_type="所属区县不一致",
                suggested_action=f"建议核实所属区县，基础资料为“{base_county}”，月报为“{county}”。",
                confidence="高",
            ))
        if (item.get("points") or item.get("professional_context")) and not (is_yes(base.get("sfzyjc")) or is_yes(base.get("zyjc"))):
            audit_rows.append(AuditRow(
                **common,
                base_name=base_name,
                issue_type="专业监测标识待补充",
                suggested_action="月报已出现专业监测点，建议将是否专业监测字段标为“是”，并补充监测点对应关系。",
                confidence="高",
            ))
    return audit_rows


def ensure_audit_table(conn) -> None:
    try:
        conn.execute(text("""
CREATE TABLE ai_gqp_base_report_audit (
  county VARCHAR(50),
  gqpbh VARCHAR(120),
  base_name VARCHAR(500),
  report_name VARCHAR(500),
  issue_type VARCHAR(100),
  suggested_action VARCHAR(1000),
  monitor_points CLOB,
  report_year INT,
  report_month INT,
  file_name VARCHAR(500),
  evidence CLOB,
  confidence VARCHAR(20),
  created_at VARCHAR(30)
)
"""))
    except Exception:
            pass


def sync_catalog_table(report_slopes: dict[str, dict]) -> None:
    db = engine()
    try:
        with db.begin() as conn:
            try:
                conn.execute(text("""
CREATE TABLE ai_gqp_report_slope_catalog (
  county VARCHAR(50),
  gqpbh VARCHAR(120),
  report_name VARCHAR(500),
  is_professional_monitor VARCHAR(10),
  monitor_points CLOB,
  report_year INT,
  report_month INT,
  file_name VARCHAR(500),
  evidence CLOB,
  mention_count INT,
  created_at VARCHAR(30)
)
"""))
            except Exception:
                pass
            conn.execute(text("DELETE FROM ai_gqp_report_slope_catalog"))
            insert_sql = text("""
INSERT INTO ai_gqp_report_slope_catalog (
  county, gqpbh, report_name, is_professional_monitor, monitor_points,
  report_year, report_month, file_name, evidence, mention_count, created_at
) VALUES (
  :county, :gqpbh, :report_name, :is_professional_monitor, :monitor_points,
  :report_year, :report_month, :file_name, :evidence, :mention_count, :created_at
)
""")
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for item in report_slopes.values():
                names = item.get("names") or {}
                report_name = ""
                mention_count = 0
                if names:
                    report_name, mention_count = sorted(names.items(), key=lambda pair: (-pair[1], len(pair[0])))[0]
                conn.execute(insert_sql, {
                    "county": item["county"],
                    "gqpbh": item["gqpbh"],
                    "report_name": report_name,
                    "is_professional_monitor": "是" if item.get("points") or item.get("professional_context") else "否",
                    "monitor_points": "、".join(sorted(item.get("points") or [])),
                    "report_year": item.get("report_year"),
                    "report_month": item.get("report_month"),
                    "file_name": item.get("file_name"),
                    "evidence": norm(item.get("evidence"))[:900],
                    "mention_count": mention_count,
                    "created_at": now,
                })
    finally:
        db.dispose()


def sync_audit_table(rows: list[AuditRow]) -> None:
    db = engine()
    try:
        with db.begin() as conn:
            ensure_audit_table(conn)
            conn.execute(text("DELETE FROM ai_gqp_base_report_audit"))
            insert_sql = text("""
INSERT INTO ai_gqp_base_report_audit (
  county, gqpbh, base_name, report_name, issue_type, suggested_action,
  monitor_points, report_year, report_month, file_name, evidence, confidence, created_at
) VALUES (
  :county, :gqpbh, :base_name, :report_name, :issue_type, :suggested_action,
  :monitor_points, :report_year, :report_month, :file_name, :evidence, :confidence, :created_at
)
""")
            for row in rows:
                conn.execute(insert_sql, asdict(row))
    finally:
        db.dispose()


def write_outputs(rows: list[AuditRow], summary: dict) -> tuple[Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "gqp_base_report_audit.json"
    csv_path = OUT_DIR / "gqp_base_report_audit.csv"
    json_path.write_text(json.dumps({"summary": summary, "rows": [asdict(row) for row in rows]}, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()) if rows else list(AuditRow.__annotations__.keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
    return json_path, csv_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync-db", action="store_true", help="写入达梦校核候选表")
    args = parser.parse_args()

    db = engine()
    try:
        with db.connect() as conn:
            base_by_code = load_base_rows(conn)
            report_rows = load_report_rows(conn)
            chunks = load_report_chunks(conn)
    finally:
        db.dispose()

    report_slopes = merge_chunk_catalog(group_report_slopes(report_rows), chunks)
    audit_rows = build_audit_rows(base_by_code, report_slopes)
    issue_counts: dict[str, int] = defaultdict(int)
    county_counts: dict[str, int] = defaultdict(int)
    for row in audit_rows:
        issue_counts[row.issue_type] += 1
        county_counts[row.county] += 1
    base_counts = defaultdict(int)
    for row in base_by_code.values():
        county = norm(row.get("ssqx"))
        if county in TARGET_COUNTIES:
            base_counts[county] += 1
    report_counts = defaultdict(int)
    for item in report_slopes.values():
        report_counts[item["county"]] += 1
    summary = {
        "base_counts": dict(sorted(base_counts.items())),
        "report_professional_slope_counts": dict(sorted(report_counts.items())),
        "audit_issue_counts": dict(sorted(issue_counts.items())),
        "audit_count_by_county": dict(sorted(county_counts.items())),
        "row_count": len(audit_rows),
    }
    json_path, csv_path = write_outputs(audit_rows, summary)
    if args.sync_db:
        sync_audit_table(audit_rows)
        sync_catalog_table(report_slopes)
    print(json.dumps({
        **summary,
        "json": str(json_path),
        "csv": str(csv_path),
        "synced_db": bool(args.sync_db),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
