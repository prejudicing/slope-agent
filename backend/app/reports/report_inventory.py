from __future__ import annotations

from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from app.core.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER


def _engine():
    return create_engine(f"dm+dmPython://{DM_USER}:{quote_plus(DM_PASSWORD)}@{DM_HOST}:{DM_PORT}/")


def get_report_asset_inventory() -> dict:
    sql = text("""
WITH docs AS (
  SELECT county, report_year, report_month,
         COUNT(*) AS doc_count,
         SUM(COALESCE(text_length, 0)) AS text_length,
         SUM(COALESCE(page_count, 0)) AS page_count
  FROM ai_monthly_report_doc
  WHERE parse_status = 'ok'
  GROUP BY county, report_year, report_month
),
monthly_values AS (
  SELECT county, report_year, report_month,
         COUNT(*) AS xyh_record_count,
         COUNT(DISTINCT gqpbh) AS professional_slope_count,
         COUNT(DISTINCT gqpbh || '-' || monitor_point) AS monitor_point_count
  FROM ai_professional_monitor_monthly_value
  GROUP BY county, report_year, report_month
),
relations AS (
  SELECT county, report_year, report_month,
         COUNT(*) AS relation_count,
         COUNT(DISTINCT gqpbh) AS relation_slope_count,
         COUNT(DISTINCT gqpbh || '-' || monitor_point) AS relation_point_count
  FROM ai_report_monitor_slope_map
  GROUP BY county, report_year, report_month
),
photos AS (
  SELECT county, report_year, report_month,
         COUNT(*) AS photo_count,
         SUM(COALESCE(image_size_kb, 0)) AS photo_size_kb
  FROM ai_report_photo_asset
  GROUP BY county, report_year, report_month
),
stability AS (
  SELECT county, report_year, report_month,
         COUNT(*) AS stability_count,
         SUM(CASE WHEN stability_level = '需现场复核' THEN 1 ELSE 0 END) AS review_count
  FROM ai_report_stability_asset
  GROUP BY county, report_year, report_month
)
SELECT
  COALESCE(d.county, m.county, r.county, p.county, s.county) AS county,
  COALESCE(d.report_year, m.report_year, r.report_year, p.report_year, s.report_year) AS report_year,
  COALESCE(d.report_month, m.report_month, r.report_month, p.report_month, s.report_month) AS report_month,
  COALESCE(d.doc_count, 0) AS doc_count,
  COALESCE(d.text_length, 0) AS text_length,
  COALESCE(d.page_count, 0) AS page_count,
  COALESCE(m.professional_slope_count, 0) AS professional_slope_count,
  COALESCE(m.monitor_point_count, 0) AS monitor_point_count,
  COALESCE(m.xyh_record_count, 0) AS xyh_record_count,
  COALESCE(r.relation_count, 0) AS relation_count,
  COALESCE(p.photo_count, 0) AS photo_count,
  COALESCE(p.photo_size_kb, 0) AS photo_size_kb,
  COALESCE(s.stability_count, 0) AS stability_count,
  COALESCE(s.review_count, 0) AS review_count
FROM docs d
FULL OUTER JOIN monthly_values m ON d.county = m.county AND d.report_year = m.report_year AND d.report_month = m.report_month
FULL OUTER JOIN relations r ON COALESCE(d.county, m.county) = r.county
  AND COALESCE(d.report_year, m.report_year) = r.report_year
  AND COALESCE(d.report_month, m.report_month) = r.report_month
FULL OUTER JOIN photos p ON COALESCE(d.county, m.county, r.county) = p.county
  AND COALESCE(d.report_year, m.report_year, r.report_year) = p.report_year
  AND COALESCE(d.report_month, m.report_month, r.report_month) = p.report_month
FULL OUTER JOIN stability s ON COALESCE(d.county, m.county, r.county, p.county) = s.county
  AND COALESCE(d.report_year, m.report_year, r.report_year, p.report_year) = s.report_year
  AND COALESCE(d.report_month, m.report_month, r.report_month, p.report_month) = s.report_month
WHERE COALESCE(d.report_year, m.report_year, r.report_year, p.report_year, s.report_year) = 2025
ORDER BY county ASC, report_month DESC
""")
    engine = _engine()
    try:
        with engine.connect() as conn:
            rows = [dict(row) for row in conn.execute(sql).mappings().all()]
    finally:
        engine.dispose()

    counties: dict[str, dict] = {}
    for row in rows:
        county = str(row.get("county") or "未标注区县")
        bucket = counties.setdefault(county, {
            "county": county,
            "doc_count": 0,
            "professional_slope_count": 0,
            "monitor_point_count": 0,
            "xyh_record_count": 0,
            "photo_count": 0,
            "stability_count": 0,
            "review_count": 0,
            "months": [],
        })
        for key in ("doc_count", "xyh_record_count", "photo_count", "stability_count", "review_count"):
            bucket[key] += int(row.get(key) or 0)
        bucket["professional_slope_count"] = max(bucket["professional_slope_count"], int(row.get("professional_slope_count") or 0))
        bucket["monitor_point_count"] = max(bucket["monitor_point_count"], int(row.get("monitor_point_count") or 0))
        bucket["months"].append({
            "month": f"{int(row.get('report_year') or 0)}-{int(row.get('report_month') or 0):02d}",
            "doc_count": int(row.get("doc_count") or 0),
            "professional_slope_count": int(row.get("professional_slope_count") or 0),
            "monitor_point_count": int(row.get("monitor_point_count") or 0),
            "xyh_record_count": int(row.get("xyh_record_count") or 0),
            "photo_count": int(row.get("photo_count") or 0),
            "stability_count": int(row.get("stability_count") or 0),
            "review_count": int(row.get("review_count") or 0),
        })

    summary = {
        "county_count": len(counties),
        "doc_count": sum(item["doc_count"] for item in counties.values()),
        "xyh_record_count": sum(item["xyh_record_count"] for item in counties.values()),
        "photo_count": sum(item["photo_count"] for item in counties.values()),
        "stability_count": sum(item["stability_count"] for item in counties.values()),
        "review_count": sum(item["review_count"] for item in counties.values()),
    }
    return {
        "status": "success",
        "title": "月报内容资产清单",
        "description": "统计2025年月报文档、专业监测点月度XYH数据、现场照片和稳定性评价沉淀情况。",
        "summary": summary,
        "counties": list(counties.values()),
    }
