from __future__ import annotations

from decimal import Decimal
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from app.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER
from app.sqlserver_db import query_sqlserver_for_display


HUBEI_COUNTIES = ("兴山县", "巴东县", "秭归县", "夷陵区")
HUBEI_BUSINESS_SLOPE_TOTAL = 525
HUBEI_BUSINESS_PROFESSIONAL_TOTAL = 129


def _to_int(value) -> int:
    if value is None:
        return 0
    if isinstance(value, Decimal):
        return int(value)
    try:
        return int(float(value))
    except Exception:
        return 0


def _to_str(value) -> str:
    return "" if value is None else str(value).strip()


def _dm_engine():
    password = quote_plus(DM_PASSWORD or "")
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def get_county_monitoring_scale() -> tuple[list[str], list[dict], int]:
    rows_by_county: dict[str, dict] = {}

    for row in _fetch_dm_scale_rows():
        county = _to_str(row.get("区县")) or "未标注区县"
        rows_by_county[county] = {
            "区县": county,
            "高切坡总数": _to_int(row.get("高切坡总数")),
            "群测群防高切坡数量": _to_int(row.get("高切坡总数")),
            "群测群防监测记录数": 0,
            "专业监测高切坡数量": _to_int(row.get("专业监测高切坡数量")),
            "专业监测点数量": _to_int(row.get("专业监测点数量")),
        }

    for row in _fetch_qmqf_scale_rows():
        county = _to_str(row.get("区县")) or "未标注区县"
        target = rows_by_county.setdefault(
            county,
            {
                "区县": county,
                "高切坡总数": 0,
                "群测群防高切坡数量": 0,
                "群测群防监测记录数": 0,
                "专业监测高切坡数量": 0,
                "专业监测点数量": 0,
            },
        )
        target["群测群防监测记录数"] = _to_int(row.get("群测群防监测记录数"))

    for row in rows_by_county.values():
        row["群测群防高切坡数量"] = row["高切坡总数"]

    rows = list(rows_by_county.values())
    rows = [row for row in rows if row["区县"] in HUBEI_COUNTIES]
    rows.sort(
        key=lambda item: (
            item["高切坡总数"],
            item["群测群防高切坡数量"],
            item["专业监测高切坡数量"],
            item["专业监测点数量"],
        ),
        reverse=True,
    )
    record_total = sum(_to_int(row.get("群测群防监测记录数")) for row in rows)
    point_total = sum(_to_int(row.get("专业监测点数量")) for row in rows)
    rows.append({
        "区县": "湖北省合计（业务核定）",
        "高切坡总数": HUBEI_BUSINESS_SLOPE_TOTAL,
        "群测群防高切坡数量": HUBEI_BUSINESS_SLOPE_TOTAL,
        "群测群防监测记录数": record_total,
        "专业监测高切坡数量": HUBEI_BUSINESS_PROFESSIONAL_TOTAL,
        "专业监测点数量": point_total,
    })
    columns = [
        "区县",
        "高切坡总数",
        "群测群防高切坡数量",
        "群测群防监测记录数",
        "专业监测高切坡数量",
        "专业监测点数量",
    ]
    return columns, rows, len(rows)


def _fetch_dm_scale_rows() -> list[dict]:
    sql = text("""
WITH base_count AS (
  SELECT
    COALESCE(ssqx, '未标注区县') AS county,
    COUNT(DISTINCT gqpbh) AS slope_count
  FROM geo_gqp_jbxx
    WHERE gqpbh IS NOT NULL
    AND gqpbh <> ''
    AND ssqx IN ('兴山县', '巴东县', '秭归县', '夷陵区')
  GROUP BY COALESCE(ssqx, '未标注区县')
),
professional_count AS (
  SELECT
    COALESCE(county, '未标注区县') AS county,
    COUNT(DISTINCT gqpbh) AS professional_slope_count,
    COUNT(DISTINCT monitor_point) AS professional_point_count
  FROM ai_professional_monitor_monthly_value
  WHERE gqpbh IS NOT NULL
    AND gqpbh <> ''
    AND county IN ('兴山县', '巴东县', '秭归县', '夷陵区')
    AND monitor_point IS NOT NULL
    AND monitor_point <> ''
    AND monitor_point NOT LIKE 'KZ%'
  GROUP BY COALESCE(county, '未标注区县')
)
SELECT
  COALESCE(b.county, p.county) AS 区县,
  COALESCE(b.slope_count, 0) AS 高切坡总数,
  COALESCE(p.professional_slope_count, 0) AS 专业监测高切坡数量,
  COALESCE(p.professional_point_count, 0) AS 专业监测点数量
FROM base_count b
FULL OUTER JOIN professional_count p ON p.county = b.county
ORDER BY 高切坡总数 DESC
""")
    engine = _dm_engine()
    try:
        with engine.connect() as conn:
            return [dict(row) for row in conn.execute(sql).mappings().all()]
    finally:
        engine.dispose()


def _fetch_qmqf_scale_rows() -> list[dict]:
    sql = """
SELECT
  COALESCE(county.areaname, city.areaname, s.location, '未标注区县') AS 区县,
  COUNT(DISTINCT m.id) AS 群测群防监测记录数
FROM tb_hcslope s
LEFT JOIN tb_hcs_monitoring m ON m.hcs_id = s.id
LEFT JOIN tb_area_china county ON s.county_id = county.areano
LEFT JOIN tb_area_china city ON s.city_id = city.areano
WHERE s.code IS NOT NULL
  AND s.code <> ''
  AND COALESCE(county.areaname, city.areaname, s.location, '未标注区县') IN ('兴山县', '巴东县', '秭归县', '夷陵区')
GROUP BY COALESCE(county.areaname, city.areaname, s.location, '未标注区县')
ORDER BY COUNT(DISTINCT s.code) DESC
""".strip()
    try:
        _, rows, _ = query_sqlserver_for_display(sql, display_limit=200)
        return rows
    except Exception as exc:
        print(f">>> [monitoring_scale] sqlserver skipped: {exc}")
        return []
