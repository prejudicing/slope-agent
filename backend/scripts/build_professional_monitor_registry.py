from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from io import BytesIO
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus
from xml.etree import ElementTree

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
from PIL import Image, ImageEnhance, ImageFilter  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from app.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER  # noqa: E402
from scripts.digitize_report_curve import digitize_chart, write_echarts_html  # noqa: E402


OUT_ROOT = BACKEND_DIR / "generated" / "professional_monitor_registry"
CHART_SOURCE_ROOT = BACKEND_DIR / "generated" / "report_chart_sources"
DIGITIZED_ROOT = BACKEND_DIR / "generated" / "report_digitized_charts"
COUNTY_KEYS = {
    "兴山县": "xingshan",
    "夷陵区": "yiling",
    "巴东县": "badong",
    "秭归县": "zigui",
}
CHART_WORDS = ("位移", "过程线", "曲线", "监测点", "累计", "变形")
MONITOR_LOOKUP_CACHE: dict[str, tuple[str, str]] = {}


@dataclass
class LatestReport:
    county: str
    report_year: int
    report_month: int
    report_type: str
    file_name: str
    file_path: str
    file_hash: str


def _engine():
    password = quote_plus(DM_PASSWORD)
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def latest_reports() -> list[LatestReport]:
    sql = text("""
SELECT county, report_year, report_month, report_type, file_name, file_path, file_hash
FROM (
  SELECT
    d.*,
    ROW_NUMBER() OVER (
      PARTITION BY d.county
      ORDER BY
        d.report_year DESC NULLS LAST,
        d.report_month DESC NULLS LAST,
        CASE
          WHEN d.report_type LIKE '%月报%' THEN 0
          WHEN d.report_type LIKE '%简报%' THEN 1
          ELSE 2
        END,
        d.file_name DESC
    ) AS rn
  FROM ai_monthly_report_doc d
  WHERE d.parse_status = 'ok'
    AND d.county IS NOT NULL
    AND d.county <> ''
    AND d.report_year IS NOT NULL
    AND d.report_month IS NOT NULL
)
WHERE rn = 1
ORDER BY county
""")
    engine = _engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql).mappings().all()
    finally:
        engine.dispose()
    return [
        LatestReport(
            county=str(row["county"]),
            report_year=int(row["report_year"]),
            report_month=int(row["report_month"]),
            report_type=str(row["report_type"] or ""),
            file_name=str(row["file_name"]),
            file_path=str(row["file_path"]),
            file_hash=str(row["file_hash"]),
        )
        for row in rows
    ]


def candidate_reports(county: str = "") -> list[LatestReport]:
    county_filter = "AND d.county = :county" if county else ""
    sql = text(f"""
SELECT county, report_year, report_month, report_type, file_name, file_path, file_hash
FROM ai_monthly_report_doc d
WHERE d.parse_status = 'ok'
  AND d.county IS NOT NULL
  AND d.county <> ''
  AND d.report_year IS NOT NULL
  AND d.report_month IS NOT NULL
  {county_filter}
ORDER BY
  d.county ASC,
  d.report_year DESC NULLS LAST,
  d.report_month DESC NULLS LAST,
  CASE
    WHEN d.report_type LIKE '%月报%' THEN 0
    WHEN d.report_type LIKE '%简报%' THEN 1
    ELSE 2
  END,
  d.file_name DESC
""")
    params = {"county": county} if county else {}
    engine = _engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
    finally:
        engine.dispose()
    return [
        LatestReport(
            county=str(row["county"]),
            report_year=int(row["report_year"]),
            report_month=int(row["report_month"]),
            report_type=str(row["report_type"] or ""),
            file_name=str(row["file_name"]),
            file_path=str(row["file_path"]),
            file_hash=str(row["file_hash"]),
        )
        for row in rows
    ]


def enhance_chart_image(image: Image.Image) -> Image.Image:
    image = image.convert("RGB")
    image = image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
    image = ImageEnhance.Contrast(image).enhance(1.25)
    image = ImageEnhance.Sharpness(image).enhance(1.8)
    return image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=130, threshold=3))


def report_key(report: LatestReport) -> str:
    county_key = COUNTY_KEYS.get(report.county, report.county)
    return f"{county_key}_{report.report_year}_{report.report_month:02d}"


def looks_like_chart(width: int, height: int) -> bool:
    if width < 420 or height < 170:
        return False
    ratio = width / max(1, height)
    return 1.6 <= ratio <= 4.2


def extract_pdf_charts(report: LatestReport, force: bool = False) -> list[dict]:
    source = Path(report.file_path)
    if not source.exists() or source.suffix.lower() != ".pdf":
        return []
    key = report_key(report)
    out_dir = CHART_SOURCE_ROOT / key
    index_path = out_dir / "index.json"
    if index_path.exists() and not force:
        return json.loads(index_path.read_text(encoding="utf-8"))

    out_dir.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(source))
    records: list[dict] = []
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        page_has_signal = any(word in page_text for word in CHART_WORDS)
        try:
            images = list(page.images)
        except Exception:
            images = []
        for image_index, image_file in enumerate(images, start=1):
            try:
                image = image_file.image
            except Exception:
                continue
            if not page_has_signal and not looks_like_chart(image.width, image.height):
                continue
            if not looks_like_chart(image.width, image.height):
                continue
            raw_name = f"page_{page_no:03d}_image_{image_index:02d}.png"
            enhanced_name = f"page_{page_no:03d}_image_{image_index:02d}_enhanced.png"
            raw_path = out_dir / raw_name
            enhanced_path = out_dir / enhanced_name
            try:
                image.save(raw_path)
                enhance_chart_image(image).save(enhanced_path)
            except Exception as exc:
                records.append({"page_no": page_no, "image_index": image_index, "error": str(exc)})
                continue
            records.append({
                "county": report.county,
                "report_year": report.report_year,
                "report_month": report.report_month,
                "file_hash": report.file_hash,
                "file_name": report.file_name,
                "page_no": page_no,
                "image_index": image_index,
                "width": image.width,
                "height": image.height,
                "raw_path": str(raw_path),
                "enhanced_path": str(enhanced_path),
                "raw_url": f"/report-assets/report_chart_sources/{key}/{raw_name}",
                "enhanced_url": f"/report-assets/report_chart_sources/{key}/{enhanced_name}",
                "page_text_excerpt": page_text[:500],
            })
    index_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return records


def extract_docx_charts(report: LatestReport, force: bool = False) -> list[dict]:
    source = Path(report.file_path)
    if not source.exists() or source.suffix.lower() != ".docx":
        return []
    key = report_key(report)
    out_dir = CHART_SOURCE_ROOT / key
    index_path = out_dir / "index.json"
    if index_path.exists() and not force:
        return json.loads(index_path.read_text(encoding="utf-8"))

    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    with zipfile.ZipFile(source) as zf:
        media_names = [
            name for name in zf.namelist()
            if name.startswith("word/media/") and Path(name).suffix.lower() in {".png", ".jpg", ".jpeg"}
        ]
        for image_index, name in enumerate(media_names, start=1):
            try:
                image = Image.open(BytesIO(zf.read(name)))
                image.load()
            except Exception:
                continue
            if not looks_like_chart(image.width, image.height):
                continue
            raw_name = f"docx_image_{image_index:03d}.png"
            enhanced_name = f"docx_image_{image_index:03d}_enhanced.png"
            raw_path = out_dir / raw_name
            enhanced_path = out_dir / enhanced_name
            try:
                image.convert("RGB").save(raw_path)
                enhance_chart_image(image).save(enhanced_path)
            except Exception as exc:
                records.append({"image_index": image_index, "error": str(exc)})
                continue
            records.append({
                "county": report.county,
                "report_year": report.report_year,
                "report_month": report.report_month,
                "file_hash": report.file_hash,
                "file_name": report.file_name,
                "page_no": None,
                "image_index": image_index,
                "width": image.width,
                "height": image.height,
                "raw_path": str(raw_path),
                "enhanced_path": str(enhanced_path),
                "raw_url": f"/report-assets/report_chart_sources/{key}/{raw_name}",
                "enhanced_url": f"/report-assets/report_chart_sources/{key}/{enhanced_name}",
                "page_text_excerpt": "",
            })
    index_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return records


def digitize_records(report: LatestReport, records: list[dict], force: bool = False) -> list[dict]:
    key = report_key(report)
    out_dir = DIGITIZED_ROOT / key
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for record in records:
        enhanced = record.get("enhanced_path")
        if not enhanced:
            continue
        image_path = Path(enhanced)
        if not image_path.exists():
            continue
        stem = image_path.stem.replace("_enhanced", "")
        data_path = out_dir / f"{stem}_digitized.json"
        html_path = out_dir / f"{stem}_echarts.html"
        if data_path.exists() and html_path.exists() and not force:
            data = json.loads(data_path.read_text(encoding="utf-8"))
        else:
            data = digitize_chart(image_path)
            data["county"] = report.county
            data["report_year"] = report.report_year
            data["report_month"] = report.report_month
            data["file_hash"] = report.file_hash
            data["file_name"] = report.file_name
            data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            write_echarts_html(data, data_path.name, html_path)
        results.append(build_mapping_item(report, record, data, data_path, html_path))
    return results


def build_docx_table_series(county_reports: list[LatestReport], force: bool = False) -> list[dict]:
    if not county_reports:
        return []
    county = county_reports[0].county
    if county != "巴东县":
        return []

    monthly_rows: dict[tuple[str, str], dict] = {}
    for report in sorted(county_reports, key=lambda item: (item.report_year, item.report_month)):
        source = Path(report.file_path)
        if source.suffix.lower() != ".docx" or not source.exists():
            continue
        for row in extract_docx_displacement_rows(source):
            key = (row["gqpbh"], row["monitor_point"])
            item = monthly_rows.setdefault(key, {
                "county": report.county,
                "gqpbh": row["gqpbh"],
                "gqpmc": row["gqpmc"],
                "monitor_point": row["monitor_point"],
                "values": [],
            })
            item["values"].append({
                "date": f"{report.report_year:04d}-{report.report_month:02d}",
                "x": row["x"],
                "y": row["y"],
                "h": row["h"],
                "file_hash": report.file_hash,
                "file_name": report.file_name,
            })

    out_dir = DIGITIZED_ROOT / "badong_table_series"
    out_dir.mkdir(parents=True, exist_ok=True)
    latest_report = max(county_reports, key=lambda item: (item.report_year, item.report_month))
    items: list[dict] = []
    for item in monthly_rows.values():
        values = _dedupe_month_values(item["values"])
        if len(values) < 2:
            continue
        data = data_from_table_series(item, values, latest_report)
        safe_name = f"badong_{_safe_filename(item['gqpbh'])}_{_safe_filename(item['monitor_point'])}"
        data_path = out_dir / f"{safe_name}_digitized.json"
        html_path = out_dir / f"{safe_name}_echarts.html"
        if force or not data_path.exists():
            data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            write_echarts_html(data, data_path.name, html_path)
        record = {
            "page_no": None,
            "image_index": None,
            "enhanced_path": "",
        }
        items.append(build_mapping_item(latest_report, record, data, data_path, html_path))
    return items


def extract_docx_displacement_rows(path: Path) -> list[dict]:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    rows: list[dict] = []
    with zipfile.ZipFile(path) as zf:
        if "word/document.xml" not in zf.namelist():
            return rows
        root = ElementTree.fromstring(zf.read("word/document.xml"))
        for tbl in root.findall(".//w:tbl", ns):
            table_rows = []
            for tr in tbl.findall("./w:tr", ns):
                cells = []
                for tc in tr.findall("./w:tc", ns):
                    texts = [node.text or "" for node in tc.findall(".//w:t", ns)]
                    cells.append("".join(texts).strip())
                if any(cells):
                    table_rows.append(cells)
            table_text = "\n".join("\t".join(row) for row in table_rows[:5])
            if "本期位移" not in table_text or "点号" not in table_text:
                continue
            rows.extend(parse_displacement_table(table_rows))
    return rows


def parse_displacement_table(table_rows: list[list[str]]) -> list[dict]:
    parsed: list[dict] = []
    current_code = ""
    current_name = ""
    for row in table_rows:
        normalized = [cell.strip() for cell in row]
        if len(normalized) < 7:
            normalized += [""] * (7 - len(normalized))
        if "编号" in normalized or "本期位移" in normalized or normalized[:3] == ["", "", ""]:
            continue
        if normalized[1]:
            current_code = normalized[1]
        if normalized[2]:
            current_name = normalized[2]
        monitor = normalized[3]
        if not current_code or not current_name or not monitor:
            continue
        try:
            x = float(normalized[4])
            y = float(normalized[5])
            h = float(normalized[6])
        except Exception:
            continue
        parsed.append({
            "gqpbh": current_code,
            "gqpmc": current_name,
            "monitor_point": monitor,
            "x": round(x, 2),
            "y": round(y, 2),
            "h": round(h, 2),
        })
    return parsed


def _dedupe_month_values(values: list[dict]) -> list[dict]:
    by_month = {item["date"]: item for item in values}
    return [by_month[key] for key in sorted(by_month)]


def data_from_table_series(item: dict, values: list[dict], latest_report: LatestReport) -> dict:
    title = f"{item['monitor_point']}（{item['gqpmc']}（{item['gqpbh']}））本期位移变化图"
    return {
        "title": title,
        "county": latest_report.county,
        "report_year": latest_report.report_year,
        "report_month": latest_report.report_month,
        "file_hash": latest_report.file_hash,
        "file_name": latest_report.file_name,
        "digitize_method": "monthly_report_table",
        "accuracy_note": "由月报表格数据生成。",
        "axis": {"x": "月报月份", "y": "本期位移（mm）"},
        "series": [
            {"name": "水平位移X", "data": [{"date": row["date"], "value": row["x"]} for row in values]},
            {"name": "水平位移Y", "data": [{"date": row["date"], "value": row["y"]} for row in values]},
            {"name": "垂直位移Z", "data": [{"date": row["date"], "value": row["h"]} for row in values]},
        ],
    }


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(value))[:80]


def build_mapping_item(report: LatestReport, record: dict, data: dict, data_path: Path, html_path: Path) -> dict:
    title = str(data.get("title") or "")
    gqpbh, slope_name, monitor_point = infer_title_fields(title, record)
    resolved = resolve_monitor_point(monitor_point)
    if resolved:
        gqpbh, slope_name = resolved
    series = data.get("series") or []
    latest_date = ""
    latest_max = 0.0
    if series and series[0].get("data"):
        latest_date = str(series[0]["data"][-1].get("date") or "")
        values = []
        for item in series[:3]:
            try:
                values.append(abs(float(item["data"][-1]["value"])))
            except Exception:
                values.append(0.0)
        latest_max = max(values) if values else 0.0
    return {
        "county": report.county,
        "report_year": report.report_year,
        "report_month": report.report_month,
        "report_type": report.report_type,
        "file_hash": report.file_hash,
        "file_name": report.file_name,
        "gqpbh": gqpbh,
        "gqpmc": slope_name,
        "monitor_point": monitor_point,
        "chart_title": title,
        "page_no": record.get("page_no"),
        "image_index": record.get("image_index"),
        "latest_monitor_date": latest_date,
        "latest_max_change": round(latest_max, 2),
        "digitized_json": str(data_path),
        "echarts_html": str(html_path),
        "chart_url": f"/report-assets/report_digitized_charts/{html_path.parent.name}/{html_path.name}",
    }


def infer_title_fields(title: str, record: dict) -> tuple[str, str, str]:
    code_match = re.search(r"（([A-Z]{1,6}\d+[A-Z0-9*]*)）", title)
    monitor_match = re.match(r"([A-Za-z]{1,10}\d+)", title)
    name_match = re.search(r"（([^（）]+高切坡[^（）]*)（", title)
    gqpbh = code_match.group(1) if code_match else ""
    monitor_point = monitor_match.group(1) if monitor_match else ""
    slope_name = name_match.group(1) if name_match else ""
    if not monitor_point:
        monitors = extract_monitor_points(record.get("page_text_excerpt", ""))
        image_index = record.get("image_index")
        if monitors and isinstance(image_index, int) and 1 <= image_index <= len(monitors):
            monitor_point = monitors[image_index - 1]
        elif monitors:
            monitor_point = monitors[0]
    if not slope_name:
        page = record.get("page_no") or ""
        idx = record.get("image_index") or ""
        if page:
            slope_name = f"第{page}页第{idx}张专业监测曲线"
        else:
            slope_name = f"第{idx}张专业监测曲线"
    if not gqpbh:
        gqpbh = slope_name
    if not monitor_point:
        monitor_point = f"P{record.get('page_no', '')}-{record.get('image_index', '')}"
    return gqpbh, slope_name, monitor_point


def extract_monitor_points(text_value: str) -> list[str]:
    patterns = [
        r"\b(?:XS|XST|YL|BD|ZG)?JC\d+[A-Z0-9-]*\b",
        r"\bBD\d{2,4}\b",
        r"\bKZ\d+[A-Z0-9-]*\b",
    ]
    values: list[str] = []
    for pattern in patterns:
        values.extend(re.findall(pattern, text_value or "", flags=re.IGNORECASE))
    result = []
    seen = set()
    for value in values:
        value = value.upper()
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def resolve_monitor_point(monitor_point: str) -> tuple[str, str] | None:
    if not monitor_point or monitor_point.startswith("P"):
        return None
    key = monitor_point.upper()
    if key in MONITOR_LOOKUP_CACHE:
        return MONITOR_LOOKUP_CACHE[key]
    sql = text("""
SELECT r.gqpbh, COALESCE(j.gqpmc, r.gqpbh) AS gqpmc
FROM (
  SELECT gqpbh
  FROM geo_wyjcsjjl
  WHERE UPPER(jcdbh) = :jcdbh
  GROUP BY gqpbh
  ORDER BY COUNT(*) DESC
  FETCH FIRST 1 ROWS ONLY
) r
LEFT JOIN geo_gqp_jbxx j ON j.gqpbh = r.gqpbh
""")
    engine = _engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(sql, {"jcdbh": key}).mappings().first()
    except Exception:
        row = None
    finally:
        engine.dispose()
    if not row:
        return None
    result = (str(row["gqpbh"]), str(row["gqpmc"]))
    MONITOR_LOOKUP_CACHE[key] = result
    return result


def write_registry(items: list[dict], reports: list[LatestReport]) -> Path:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "description": "区县最新月报专业监测点与高切坡对应关系台账",
        "reports": [report.__dict__ for report in reports],
        "items": items,
    }
    path = OUT_ROOT / "registry.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for county in sorted({item["county"] for item in items}):
        county_path = OUT_ROOT / f"{COUNTY_KEYS.get(county, county)}.json"
        county_items = [item for item in items if item["county"] == county]
        county_path.write_text(json.dumps(county_items, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def sync_to_dm(items: list[dict]) -> None:
    engine = _engine()
    try:
        with engine.begin() as conn:
            try:
                conn.execute(text("""
CREATE TABLE ai_professional_monitor_point_map (
  county VARCHAR(50),
  report_year INT,
  report_month INT,
  report_type VARCHAR(80),
  file_hash VARCHAR(128),
  file_name VARCHAR(500),
  gqpbh VARCHAR(120),
  gqpmc VARCHAR(500),
  monitor_point VARCHAR(120),
  chart_title VARCHAR(500),
  page_no INT,
  image_index INT,
  latest_monitor_date VARCHAR(20),
  latest_max_change DECIMAL(18,2),
  digitized_json VARCHAR(1000),
  echarts_html VARCHAR(1000),
  chart_url VARCHAR(1000)
)
"""))
            except Exception:
                pass
            for report_hash in sorted({item["file_hash"] for item in items}):
                conn.execute(text("DELETE FROM ai_professional_monitor_point_map WHERE file_hash = :file_hash"), {"file_hash": report_hash})
            insert_sql = text("""
INSERT INTO ai_professional_monitor_point_map (
  county, report_year, report_month, report_type, file_hash, file_name,
  gqpbh, gqpmc, monitor_point, chart_title, page_no, image_index,
  latest_monitor_date, latest_max_change, digitized_json, echarts_html, chart_url
) VALUES (
  :county, :report_year, :report_month, :report_type, :file_hash, :file_name,
  :gqpbh, :gqpmc, :monitor_point, :chart_title, :page_no, :image_index,
  :latest_monitor_date, :latest_max_change, :digitized_json, :echarts_html, :chart_url
)
""")
            for item in items:
                conn.execute(insert_sql, item)
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--county", default="", help="只更新指定区县")
    parser.add_argument("--force", action="store_true", help="强制重新抽图和生成")
    parser.add_argument("--sync-db", action="store_true", help="同步写入达梦对应关系表")
    args = parser.parse_args()

    candidates = candidate_reports(args.county)
    counties = []
    for report in candidates:
        if report.county not in counties:
            counties.append(report.county)
    selected_reports: list[LatestReport] = []
    items: list[dict] = []
    for county in counties:
        county_reports = [report for report in candidates if report.county == county]
        table_items = build_docx_table_series(county_reports, force=args.force)
        if table_items:
            selected_reports.append(max(county_reports, key=lambda item: (item.report_year, item.report_month)))
            items.extend(table_items)
            continue
        for report in county_reports:
            source = Path(report.file_path)
            if source.suffix.lower() == ".pdf":
                records = extract_pdf_charts(report, force=args.force)
            elif source.suffix.lower() == ".docx":
                records = extract_docx_charts(report, force=args.force)
            else:
                records = []
            report_items = digitize_records(report, records, force=args.force)
            if report_items:
                selected_reports.append(report)
                items.extend(report_items)
                break
        else:
            if county_reports:
                selected_reports.append(county_reports[0])

    registry_path = write_registry(items, selected_reports)
    if args.sync_db and items:
        sync_to_dm(items)
    print(json.dumps({
        "reports": len(selected_reports),
        "items": len(items),
        "registry": str(registry_path),
        "synced_db": bool(args.sync_db and items),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
