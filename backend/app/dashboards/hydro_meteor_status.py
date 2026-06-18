from __future__ import annotations

import re
from decimal import Decimal
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from app.core.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER


SLOPE_CODE_RE = re.compile(r"(?<![A-Z0-9])[A-Z]{1,4}\d{3,5}[A-Z]?\*?(?![A-Z0-9])", re.IGNORECASE)
COUNTY_ALIASES = {
    "巴东": "巴东县",
    "巴东县": "巴东县",
    "秭归": "秭归县",
    "秭归县": "秭归县",
    "兴山": "兴山县",
    "兴山县": "兴山县",
    "夷陵": "夷陵区",
    "夷陵区": "夷陵区",
}


def get_hydro_meteor_status(question: str) -> tuple[list[str], list[dict], int]:
    context = _resolve_context(question)
    code = context.get("gqpbh", "")
    county = context.get("county", "")
    if not code and not county:
        return ["项目", "内容"], [{
            "项目": "查询提示",
            "内容": "暂未识别到高切坡编号或区县。请先绑定当前高切坡，或补充区县、编号后查询降雨和水位情况。",
        }], 1

    rain = _fetch_rainfall(code=code, county=county)
    water = _fetch_water_level(code=code, county=county)
    rows = [
        {
            "项目": "对象",
            "内容": _object_text(context),
        },
        {
            "项目": "降雨",
            "内容": _rain_text(rain),
        },
        {
            "项目": "水位",
            "内容": _water_text(water),
        },
        {
            "项目": "综合研判",
            "内容": _risk_text(rain, water),
        },
    ]
    return ["项目", "内容"], rows, len(rows)


def _engine():
    password = quote_plus(DM_PASSWORD or "")
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def _resolve_context(question: str) -> dict:
    code_match = SLOPE_CODE_RE.search((question or "").upper())
    code = code_match.group(0).upper() if code_match else ""
    county = _extract_county(question)
    engine = _engine()
    try:
        with engine.connect() as conn:
            row = None
            if code:
                row = conn.execute(text("""
SELECT GQPBH AS gqpbh, GQPMC AS gqpmc, SSQX AS county, SSJD AS township, X AS longitude, Y AS latitude
FROM geo_gqp_jbxx
WHERE UPPER(GQPBH) = :code
FETCH FIRST 1 ROWS ONLY
"""), {"code": code}).mappings().first()
            if not row and county:
                row = conn.execute(text("""
SELECT '' AS gqpbh, '' AS gqpmc, :county AS county, '' AS township, '' AS longitude, '' AS latitude
FROM DUAL
"""), {"county": county}).mappings().first()
            return dict(row or {})
    except Exception:
        return {"gqpbh": code, "county": county}
    finally:
        engine.dispose()


def _extract_county(question: str) -> str:
    compact = "".join((question or "").split())
    for alias, county in COUNTY_ALIASES.items():
        if alias in compact:
            return county
    return ""


def _fetch_rainfall(*, code: str, county: str) -> dict:
    sql = """
SELECT
  station_code,
  station_name,
  county,
  observation_time,
  rain_1h_mm,
  rain_3h_mm,
  rain_24h_mm,
  rain_72h_mm,
  warning_level,
  data_source,
  fetched_at
FROM ai_weather_rainfall_cache
WHERE (:code = '' OR gqpbh = :code OR gqpbh IS NULL OR gqpbh = '')
  AND (:county = '' OR county = :county)
ORDER BY
  CASE WHEN gqpbh = :code THEN 0 ELSE 1 END,
  CASE
    WHEN station_code = '60107300' THEN 0
    WHEN station_code = '60105400' THEN 1
    WHEN station_code = '60108300' THEN 2
    ELSE 9
  END,
  observation_time DESC NULLS LAST,
  fetched_at DESC NULLS LAST
FETCH FIRST 1 ROWS ONLY
"""
    return _fetch_optional(sql, {"code": code, "county": county})


def _fetch_water_level(*, code: str, county: str) -> dict:
    preferred = _fetch_optional("""
SELECT
  station_code,
  station_name,
  river_name,
  observation_time,
  water_level_m,
  change_24h_m,
  change_72h_m,
  flow_m3s,
  warning_level_m,
  data_source,
  fetched_at
FROM ai_hydro_water_level_cache
WHERE (:code = '' OR gqpbh = :code)
ORDER BY observation_time DESC NULLS LAST, fetched_at DESC NULLS LAST
FETCH FIRST 1 ROWS ONLY
""", {"code": code})
    if preferred:
        return preferred

    three_gorges = _fetch_optional("""
SELECT
  station_code,
  station_name,
  river_name,
  observation_time,
  water_level_m,
  change_24h_m,
  change_72h_m,
  flow_m3s,
  warning_level_m,
  data_source,
  fetched_at
FROM ai_hydro_water_level_cache
WHERE station_code = '60107300'
ORDER BY observation_time DESC NULLS LAST, fetched_at DESC NULLS LAST
FETCH FIRST 1 ROWS ONLY
""", {})
    if three_gorges:
        return three_gorges

    sql = """
SELECT
  station_code,
  station_name,
  river_name,
  observation_time,
  water_level_m,
  change_24h_m,
  change_72h_m,
  flow_m3s,
  warning_level_m,
  data_source,
  fetched_at
FROM ai_hydro_water_level_cache
WHERE (:code = '' OR gqpbh = :code OR gqpbh IS NULL OR gqpbh = '')
  AND (:county = '' OR county = :county OR county IS NULL OR county = '')
ORDER BY
  CASE WHEN gqpbh = :code THEN 0 ELSE 1 END,
  observation_time DESC NULLS LAST,
  fetched_at DESC NULLS LAST
FETCH FIRST 1 ROWS ONLY
"""
    return _fetch_optional(sql, {"code": code, "county": county})


def _fetch_optional(sql: str, params: dict) -> dict:
    engine = _engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(text(sql), params).mappings().first()
            return dict(row or {})
    except Exception:
        return {}
    finally:
        engine.dispose()


def _object_text(context: dict) -> str:
    name = context.get("gqpmc") or "当前对象"
    code = context.get("gqpbh") or ""
    county = context.get("county") or "区县待核实"
    township = context.get("township") or ""
    location = township if township.startswith(county) else f"{county}{township}"
    if code:
        return f"{location}，{name}（{code}）。"
    return f"{county}范围内高切坡。"


def _rain_text(row: dict) -> str:
    if not row:
        return "中间库暂未检索到有效降雨缓存数据；现场可先按最近一次监测和巡查记录开展判断。"
    station = row.get("station_name") or row.get("station_code") or "邻近雨量站"
    obs = _fmt_time(row.get("observation_time"))
    rain24 = _fmt(row.get("rain_24h_mm"))
    rain72 = _fmt(row.get("rain_72h_mm"))
    rain1 = _fmt(row.get("rain_1h_mm"))
    warning = row.get("warning_level") or "暂无预警标记"
    return f"{station}最新观测时间为{obs}，近1小时降雨{rain1}毫米，近24小时累计降雨{rain24}毫米，近72小时累计降雨{rain72}毫米；当前雨量预警标记为{warning}。"


def _water_text(row: dict) -> str:
    if not row:
        return "中间库暂未检索到有效水位缓存数据；如涉及库岸坡体，应补充三峡库水位或就近水文站水位。"
    station = row.get("station_name") or row.get("station_code") or "邻近水文站"
    river = row.get("river_name") or ""
    obs = _fmt_time(row.get("observation_time"))
    level = _fmt(row.get("water_level_m"))
    change24 = _fmt_signed(row.get("change_24h_m"))
    change72 = _fmt_signed(row.get("change_72h_m"))
    river_text = f"{river}" if river else ""
    return f"{river_text}{station}最新观测时间为{obs}，水位{level}米，较24小时前变化{change24}米，较72小时前变化{change72}米。"


def _risk_text(rain: dict, water: dict) -> str:
    if not rain and not water:
        return "当前未取得降雨和水位缓存数据，暂不宜单独依据外部环境因子作出风险判断；建议结合专业监测、群测群防巡查和现场照片复核。"
    rain24 = _to_float(rain.get("rain_24h_mm")) if rain else 0.0
    rain72 = _to_float(rain.get("rain_72h_mm")) if rain else 0.0
    water_change = abs(_to_float(water.get("change_24h_m"))) if water else 0.0
    if rain24 >= 50 or rain72 >= 100 or water_change >= 1.0:
        return "近期外部环境变化较明显，建议提高巡查频次，重点核查裂缝、挡墙开裂、坡脚渗水和排水不畅部位，并结合专业监测曲线判断是否存在雨后或水位变动响应。"
    if rain24 >= 25 or rain72 >= 50 or water_change >= 0.3:
        return "近期存在一定降雨或水位变化，建议保持常规跟踪并关注专业监测点是否出现同步位移增大。"
    return "近期降雨和水位变化暂未达到明显触发条件，可结合常规监测和现场巡查继续跟踪。"


def _fmt(value) -> str:
    number = _to_float(value)
    return f"{number:.1f}"


def _fmt_signed(value) -> str:
    number = _to_float(value)
    return f"{number:+.2f}"


def _fmt_time(value) -> str:
    text_value = str(value or "").replace("T", " ").strip()
    return text_value[:16] if text_value else "时间待更新"


def _to_float(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except Exception:
        return 0.0
