from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
REPORT_EXTRACT_DIR = BACKEND_DIR / "report_extract"
OUT_DIR = BACKEND_DIR / "generated" / "monthly_report_asset_audit"
BUNDLED_SITE_PACKAGES = Path(
    r"C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages"
)

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if BUNDLED_SITE_PACKAGES.exists() and str(BUNDLED_SITE_PACKAGES) not in sys.path:
    sys.path.append(str(BUNDLED_SITE_PACKAGES))

from sqlalchemy import create_engine, text  # noqa: E402

from app.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER  # noqa: E402


COUNTIES = ("巴东县", "兴山县", "夷陵区", "秭归县")
STABILITY_WORDS = ("稳定", "较稳定", "基本稳定", "总体稳定", "总体较为稳定", "一般", "较差", "异常", "失稳")
PROBLEM_WORDS = ("裂缝", "落石", "掉块", "挡墙开裂", "道路开裂", "坡面破坏", "变形", "冲刷", "排水", "隐患", "异常")
PHOTO_WORDS = ("照片", "现场照片", "图片", "影像", "巡查照片", "全景")
CHART_WORDS = ("位移", "过程线", "曲线", "累计", "监测点", "变形")


@dataclass
class AuditResult:
    generated_at: str
    report_docs: dict
    professional_relation: dict
    monthly_xyh: dict
    historical_charts: dict
    stability_and_photos: dict
    recommendations: list[str]


def dm_engine():
    password = quote_plus(DM_PASSWORD)
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def fetch_all(conn, sql: str, params: dict | None = None) -> list[dict]:
    rows = conn.execute(text(sql), params or {}).mappings().all()
    return [{key: row.get(key) for key in row.keys()} for row in rows]


def load_json(path: Path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


def short_text(value: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", "", str(value or ""))
    return value[:limit]


def sentence_candidates(text_value: str) -> list[str]:
    text_value = re.sub(r"\s+", "", text_value or "")
    pieces = re.split(r"[。；;]", text_value)
    result = []
    for piece in pieces:
        if 18 <= len(piece) <= 220 and any(word in piece for word in STABILITY_WORDS + PROBLEM_WORDS):
            result.append(piece)
    return result


def audit_report_docs(conn) -> dict:
    by_county = fetch_all(conn, """
SELECT
  county,
  COUNT(*) AS doc_count,
  SUM(CASE WHEN report_year = 2025 THEN 1 ELSE 0 END) AS doc_2025_count,
  MIN(report_year) AS min_year,
  MAX(report_year) AS max_year,
  MAX(report_year * 100 + COALESCE(report_month, 0)) AS latest_period,
  SUM(CASE WHEN report_type LIKE '%年报%' OR report_type LIKE '%成果报告%' THEN 1 ELSE 0 END) AS annual_count,
  SUM(CASE WHEN report_type LIKE '%月报%' OR report_type LIKE '%简报%' THEN 1 ELSE 0 END) AS monthly_count
FROM ai_monthly_report_doc
WHERE parse_status = 'ok'
  AND county IN ('巴东县','兴山县','夷陵区','秭归县')
GROUP BY county
ORDER BY county
""")
    latest = fetch_all(conn, """
SELECT county, report_year, report_month, report_type, file_name
FROM (
  SELECT d.*,
         ROW_NUMBER() OVER (
           PARTITION BY county
           ORDER BY report_year DESC NULLS LAST,
                    report_month DESC NULLS LAST,
                    CASE WHEN report_type LIKE '%月报%' THEN 0 WHEN report_type LIKE '%简报%' THEN 1 ELSE 2 END,
                    file_name DESC
         ) AS rn
  FROM ai_monthly_report_doc d
  WHERE parse_status = 'ok'
    AND county IN ('巴东县','兴山县','夷陵区','秭归县')
    AND report_year IS NOT NULL
)
WHERE rn = 1
ORDER BY county
""")
    return {"by_county": by_county, "latest_by_county": latest}


def audit_professional_relation(conn) -> dict:
    relation = fetch_all(conn, """
SELECT
  county,
  COUNT(*) AS relation_rows,
  COUNT(DISTINCT gqpbh) AS slope_count,
  COUNT(DISTINCT gqpbh || '::' || monitor_point) AS point_count,
  SUM(CASE WHEN source_type LIKE '%监测成果表%' THEN 1 ELSE 0 END) AS table_relation_rows,
  SUM(CASE WHEN confidence = '高' THEN 1 ELSE 0 END) AS high_confidence_rows
FROM ai_report_monitor_slope_map
WHERE county IN ('巴东县','兴山县','夷陵区','秭归县')
  AND monitor_point IS NOT NULL
  AND monitor_point <> ''
  AND monitor_point NOT LIKE 'KZ%'
GROUP BY county
ORDER BY county
""")
    monthly_relation = fetch_all(conn, """
SELECT
  county,
  COUNT(DISTINCT gqpbh) AS slope_count,
  COUNT(DISTINCT gqpbh || '::' || monitor_point) AS point_count
FROM ai_professional_monitor_monthly_value
WHERE report_year = 2025
  AND county IN ('巴东县','兴山县','夷陵区','秭归县')
  AND monitor_point IS NOT NULL
  AND monitor_point <> ''
  AND monitor_point NOT LIKE 'KZ%'
GROUP BY county
ORDER BY county
""")
    return {"relation_table": relation, "monthly_value_table": monthly_relation}


def audit_monthly_xyh(conn) -> dict:
    summary = fetch_all(conn, """
SELECT
  county,
  COUNT(*) AS value_rows,
  COUNT(DISTINCT gqpbh) AS slope_count,
  COUNT(DISTINCT gqpbh || '::' || monitor_point) AS point_count,
  COUNT(DISTINCT report_month) AS month_count,
  MIN(report_month) AS min_month,
  MAX(report_month) AS max_month
FROM ai_professional_monitor_monthly_value
WHERE report_year = 2025
  AND county IN ('巴东县','兴山县','夷陵区','秭归县')
  AND monitor_point IS NOT NULL
  AND monitor_point <> ''
  AND monitor_point NOT LIKE 'KZ%'
GROUP BY county
ORDER BY county
""")
    continuity = fetch_all(conn, """
WITH point_months AS (
  SELECT county, gqpbh, monitor_point, COUNT(DISTINCT report_month) AS month_count
  FROM ai_professional_monitor_monthly_value
  WHERE report_year = 2025
    AND county IN ('巴东县','兴山县','夷陵区','秭归县')
    AND monitor_point IS NOT NULL
    AND monitor_point <> ''
    AND monitor_point NOT LIKE 'KZ%'
  GROUP BY county, gqpbh, monitor_point
)
SELECT
  county,
  SUM(CASE WHEN month_count >= 9 THEN 1 ELSE 0 END) AS points_9_plus_months,
  SUM(CASE WHEN month_count BETWEEN 6 AND 8 THEN 1 ELSE 0 END) AS points_6_to_8_months,
  SUM(CASE WHEN month_count BETWEEN 2 AND 5 THEN 1 ELSE 0 END) AS points_2_to_5_months,
  SUM(CASE WHEN month_count = 1 THEN 1 ELSE 0 END) AS points_1_month
FROM point_months
GROUP BY county
ORDER BY county
""")
    top_points = fetch_all(conn, """
WITH point_sum AS (
  SELECT
    county,
    gqpbh,
    MAX(gqpmc) AS gqpmc,
    monitor_point,
    COUNT(DISTINCT report_month) AS month_count,
    SUM(COALESCE(current_x, 0)) AS x_sum,
    SUM(COALESCE(current_y, 0)) AS y_sum,
    SUM(COALESCE(current_h, 0)) AS h_sum
  FROM ai_professional_monitor_monthly_value
  WHERE report_year = 2025
    AND county IN ('巴东县','兴山县','夷陵区','秭归县')
    AND monitor_point IS NOT NULL
    AND monitor_point <> ''
    AND monitor_point NOT LIKE 'KZ%'
  GROUP BY county, gqpbh, monitor_point
)
SELECT *
FROM (
  SELECT
    county,
    gqpbh,
    gqpmc,
    monitor_point,
    month_count,
    ROUND(x_sum, 2) AS x_sum,
    ROUND(y_sum, 2) AS y_sum,
    ROUND(h_sum, 2) AS h_sum,
    ROUND(GREATEST(ABS(x_sum), ABS(y_sum), ABS(h_sum)), 2) AS max_abs_change
  FROM point_sum
  ORDER BY GREATEST(ABS(x_sum), ABS(y_sum), ABS(h_sum)) DESC
)
WHERE ROWNUM <= 20
""")
    possible_outliers = [
        row for row in top_points
        if float(row.get("max_abs_change") or 0) >= 20
    ]
    return {
        "summary_by_county": summary,
        "continuity_by_county": continuity,
        "top_points_by_signed_sum": top_points,
        "possible_outliers_over_20mm": possible_outliers,
        "calculation_note": "按同一监测点2025年各月X/Y/H本期变化量带正负求和，取三个方向绝对值最大者作为年度变化量参考。",
    }


def audit_historical_charts(conn) -> dict:
    point_map = fetch_all(conn, """
SELECT
  county,
  COUNT(*) AS chart_rows,
  COUNT(DISTINCT gqpbh) AS slope_count,
  COUNT(DISTINCT gqpbh || '::' || monitor_point) AS point_count,
  SUM(CASE WHEN chart_url IS NOT NULL AND chart_url <> '' THEN 1 ELSE 0 END) AS chart_url_count
FROM ai_professional_monitor_point_map
WHERE county IN ('巴东县','兴山县','夷陵区','秭归县')
GROUP BY county
ORDER BY county
""")
    sample_charts = fetch_all(conn, """
SELECT county, gqpbh, gqpmc, monitor_point, chart_title, page_no, image_index, chart_url
FROM ai_professional_monitor_point_map
WHERE county IN ('巴东县','兴山县','夷陵区','秭归县')
  AND chart_url IS NOT NULL
  AND chart_url <> ''
FETCH FIRST 20 ROWS ONLY
""")
    asset_summary = load_json(REPORT_EXTRACT_DIR / "report_asset_summary.json", {})
    chart_source_count = 0
    chart_source_dirs = BACKEND_DIR.joinpath("generated", "report_chart_sources")
    if chart_source_dirs.exists():
        for index_path in chart_source_dirs.glob("*/index.json"):
            try:
                chart_source_count += len(json.loads(index_path.read_text(encoding="utf-8")))
            except Exception:
                continue
    return {
        "point_map_by_county": point_map,
        "sample_chart_links": sample_charts,
        "asset_index_summary": asset_summary,
        "extracted_chart_image_count": chart_source_count,
    }


def audit_stability_and_photos(conn) -> dict:
    chunks = fetch_all(conn, """
SELECT county, report_year, report_month, report_type, file_hash, chunk_index, content
FROM ai_monthly_report_chunk
WHERE county IN ('巴东县','兴山县','夷陵区','秭归县')
  AND content IS NOT NULL
  AND (
    content LIKE '%稳定%'
    OR content LIKE '%异常%'
    OR content LIKE '%裂缝%'
    OR content LIKE '%落石%'
    OR content LIKE '%照片%'
    OR content LIKE '%现场%'
  )
ORDER BY county, report_year DESC NULLS LAST, report_month DESC NULLS LAST, chunk_index
""")
    by_county = defaultdict(lambda: {"stability_chunks": 0, "problem_chunks": 0, "photo_text_chunks": 0, "examples": []})
    for chunk in chunks:
        content = str(chunk.get("content") or "")
        county = str(chunk.get("county") or "未识别")
        has_stability = any(word in content for word in STABILITY_WORDS)
        has_problem = any(word in content for word in PROBLEM_WORDS)
        has_photo = any(word in content for word in PHOTO_WORDS)
        if has_stability:
            by_county[county]["stability_chunks"] += 1
        if has_problem:
            by_county[county]["problem_chunks"] += 1
        if has_photo:
            by_county[county]["photo_text_chunks"] += 1
        if len(by_county[county]["examples"]) < 5 and (has_stability or has_problem):
            sentences = sentence_candidates(content)
            by_county[county]["examples"].append({
                "period": f"{chunk.get('report_year') or ''}-{int(chunk.get('report_month') or 0):02d}" if chunk.get("report_month") else str(chunk.get("report_year") or ""),
                "report_type": chunk.get("report_type"),
                "chunk_index": chunk.get("chunk_index"),
                "snippet": short_text(sentences[0] if sentences else content, 220),
            })

    pages = load_jsonl(REPORT_EXTRACT_DIR / "report_page_index.jsonl")
    photo_pages = [page for page in pages if page.get("asset_type") == "现场照片/图片"]
    risk_photo_pages = [
        page for page in photo_pages
        if int(page.get("risk_score") or 0) > 0 or any(word in str(page.get("text_excerpt") or "") for word in PROBLEM_WORDS)
    ]
    page_counts = Counter(page.get("county") or "未识别" for page in photo_pages)
    risk_page_counts = Counter(page.get("county") or "未识别" for page in risk_photo_pages)
    examples = []
    for page in risk_photo_pages[:30]:
        examples.append({
            "county": page.get("county"),
            "file_name": page.get("file_name"),
            "page_no": page.get("page_no"),
            "image_count": page.get("image_count"),
            "asset_type": page.get("asset_type"),
            "slope_codes": page.get("slope_codes"),
            "monitor_points": page.get("monitor_points"),
            "text_excerpt": short_text(page.get("text_excerpt"), 180),
        })
    return {
        "text_summary_by_county": dict(by_county),
        "photo_pages_by_county": dict(page_counts),
        "risk_related_photo_pages_by_county": dict(risk_page_counts),
        "risk_photo_page_examples": examples,
    }


def make_recommendations(result: dict) -> list[str]:
    return [
        "将ai_report_monitor_slope_map作为“专业监测坡-监测点关系”候选表，后续需以最新月报和年报逐县复核后固化为正式关系表。",
        "将ai_professional_monitor_monthly_value作为专业监测分析主表，年度累计统一采用本期XYH变化量带正负逐月求和，避免直接叠加累计值导致偏大。",
        "折线图优先由月度XYH表重绘；历史曲线图作为原始佐证图保留，可在详情弹窗中并列查看。",
        "稳定性评价应从月报结论段抽取并与高切坡编号、名称关联；评价一般或含异常描述的坡优先匹配邻近现场照片。",
        "下一步建议新增月报照片抽取表，保存图片文件路径、页码、邻近文本、坡号、点号和异常关键词，供业务简报和PDF直接引用。",
    ]


def write_outputs(result: AuditResult) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = asdict(result)
    (OUT_DIR / "monthly_report_asset_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    lines = [
        "# 月报内容资产梳理",
        "",
        f"生成时间：{result.generated_at}",
        "",
        "## 1. 月报覆盖情况",
    ]
    for row in result.report_docs.get("by_county", []):
        latest = next((item for item in result.report_docs.get("latest_by_county", []) if item.get("county") == row.get("county")), {})
        lines.append(
            f"- {row.get('county')}：已入库报告 {row.get('doc_count')} 份，其中2025年 {row.get('doc_2025_count')} 份；"
            f"最新主报告为 {latest.get('report_year')}-{int(latest.get('report_month') or 0):02d}《{latest.get('file_name') or ''}》。"
        )
    lines.extend(["", "## 2. 专业监测坡与监测点关系"])
    for row in result.professional_relation.get("monthly_value_table", []):
        lines.append(f"- {row.get('county')}：月度值表识别专业监测坡 {row.get('slope_count')} 处、监测点 {row.get('point_count')} 个。")
    lines.extend(["", "## 3. 月度XYH位移数据"])
    for row in result.monthly_xyh.get("summary_by_county", []):
        lines.append(
            f"- {row.get('county')}：2025年月度XYH记录 {row.get('value_rows')} 条，覆盖 {row.get('slope_count')} 处坡、"
            f"{row.get('point_count')} 个点，月份范围 {row.get('min_month')}-{row.get('max_month')} 月。"
        )
    lines.append("")
    lines.append("年度变化量较大的点位样本：")
    for row in result.monthly_xyh.get("top_points_by_signed_sum", [])[:8]:
        lines.append(
            f"- {row.get('county')} {row.get('gqpmc')}（{row.get('gqpbh')}）{row.get('monitor_point')}："
            f"X={row.get('x_sum')}mm，Y={row.get('y_sum')}mm，H={row.get('h_sum')}mm，最大方向={row.get('max_abs_change')}mm。"
        )
    lines.extend(["", "## 4. 历史曲线图"])
    for row in result.historical_charts.get("point_map_by_county", []):
        lines.append(
            f"- {row.get('county')}：已建立历史曲线/点位索引 {row.get('chart_rows')} 条，涉及 {row.get('slope_count')} 处坡、"
            f"{row.get('point_count')} 个点。"
        )
    asset_summary = result.historical_charts.get("asset_index_summary", {})
    if asset_summary:
        lines.append(
            f"- 本地资产索引共识别疑似曲线页 {asset_summary.get('chart_pages')} 页、照片页 {asset_summary.get('photo_pages')} 页、"
            f"图片资产 {asset_summary.get('images')} 张。"
        )
    lines.extend(["", "## 5. 稳定性评价与现场照片"])
    for county, item in result.stability_and_photos.get("text_summary_by_county", {}).items():
        lines.append(
            f"- {county}：含稳定性表述片段 {item.get('stability_chunks')} 个，含异常/问题片段 {item.get('problem_chunks')} 个，"
            f"含照片文字片段 {item.get('photo_text_chunks')} 个。"
        )
    risk_counts = result.stability_and_photos.get("risk_related_photo_pages_by_county", {})
    if risk_counts:
        lines.append("- 与异常描述相关的疑似现场照片页：" + "、".join(f"{county}{count}页" for county, count in risk_counts.items()))
    lines.extend(["", "## 6. 建议"])
    lines.extend(f"- {item}" for item in result.recommendations)
    (OUT_DIR / "monthly_report_asset_audit.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    engine = dm_engine()
    try:
        with engine.connect() as conn:
            result = AuditResult(
                generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                report_docs=audit_report_docs(conn),
                professional_relation=audit_professional_relation(conn),
                monthly_xyh=audit_monthly_xyh(conn),
                historical_charts=audit_historical_charts(conn),
                stability_and_photos=audit_stability_and_photos(conn),
                recommendations=[],
            )
    finally:
        engine.dispose()
    result.recommendations = make_recommendations(asdict(result))
    write_outputs(result)
    print(json.dumps({
        "out_dir": str(OUT_DIR),
        "markdown": str(OUT_DIR / "monthly_report_asset_audit.md"),
        "json": str(OUT_DIR / "monthly_report_asset_audit.json"),
        "generated_at": result.generated_at,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
