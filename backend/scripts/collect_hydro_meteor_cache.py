"""Collect rainfall and water-level data into the local middle cache.

Recommended demo mode:
  WEATHER_PROVIDER=open_meteo
  HYDRO_METEOR_TARGETS=ZG0098,ZG0095
  WATER_PROVIDER=cjh_public

The script is deliberately adapter based. The high-cut-slope system only reads
the cache tables, so later replacing public pages with an authorized hydrology
interface does not affect the question-answering module.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests
import urllib3
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import get_sqlalchemy_engine  # noqa: E402


WEATHER_PROVIDER = os.getenv("WEATHER_PROVIDER", "open_meteo").strip().lower()
WATER_PROVIDER = os.getenv("WATER_PROVIDER", "cjh_public").strip().lower()
HYDRO_METEOR_TARGETS = [x.strip().upper() for x in os.getenv("HYDRO_METEOR_TARGETS", "").split(",") if x.strip()]

OPEN_METEO_BASE_URL = os.getenv("OPEN_METEO_BASE_URL", "https://api.open-meteo.com").rstrip("/")

QWEATHER_API_KEY = os.getenv("QWEATHER_API_KEY", "").strip()
QWEATHER_BASE_URL = os.getenv("QWEATHER_BASE_URL", "https://devapi.qweather.com").rstrip("/")

SENIVERSE_API_KEY = os.getenv("SENIVERSE_API_KEY", "").strip()
SENIVERSE_BASE_URL = os.getenv("SENIVERSE_BASE_URL", "https://api.seniverse.com").rstrip("/")

RAIN_API_URL = os.getenv("RAIN_API_URL", "").strip()
RAIN_API_KEY = os.getenv("RAIN_API_KEY", "").strip()
WATER_LEVEL_API_URL = os.getenv("WATER_LEVEL_API_URL", "").strip()
WATER_LEVEL_API_KEY = os.getenv("WATER_LEVEL_API_KEY", "").strip()

CJH_WATER_URL = os.getenv("CJH_WATER_URL", "https://www.cjh.com.cn/sssqcwww.html").strip()


class SimpleTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_cell = False
        self.current_cell: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"td", "th"}:
            self.in_cell = True
            self.current_cell = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self.in_cell:
            text_value = re.sub(r"\s+", " ", "".join(self.current_cell)).strip()
            self.current_row.append(text_value)
            self.in_cell = False
        elif tag == "tr" and self.current_row:
            self.rows.append(self.current_row)
            self.current_row = []


def fetch_json(url: str, api_key: str = "", *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if not url:
        return {}
    headers = {"User-Agent": "gqp-hydro-meteor-collector/1.0"}
    if api_key and "key" not in (params or {}):
        headers["Authorization"] = f"Bearer {api_key}"
    response = requests.get(url, headers=headers, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def fetch_text(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 gqp-hydro-meteor-collector/1.0"}
    candidates: list[tuple[str, bool]] = [(url, True)]
    if url.startswith("https://"):
        candidates.append((url, False))
        candidates.append(("http://" + url.removeprefix("https://"), True))
    last_error: Exception | None = None
    for candidate_url, verify_tls in candidates:
        try:
            if not verify_tls:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.get(candidate_url, headers=headers, timeout=25, verify=verify_tls)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or response.encoding
            return response.text
        except requests.exceptions.RequestException as exc:
            last_error = exc
    raise last_error or RuntimeError(f"failed to fetch {url}")


def get_targets(conn) -> list[dict[str, Any]]:
    params = {}
    where = ""
    if HYDRO_METEOR_TARGETS:
        placeholders = []
        for index, code in enumerate(HYDRO_METEOR_TARGETS):
            key = f"code_{index}"
            placeholders.append(f":{key}")
            params[key] = code
        where = f"WHERE UPPER(j.GQPBH) IN ({','.join(placeholders)})"

    rows = conn.execute(text(f"""
SELECT
  j.GQPBH AS gqpbh,
  j.GQPMC AS gqpmc,
  j.SSQX AS county,
  j.SSJD AS township,
  j.X AS longitude,
  j.Y AS latitude,
  m.rain_station_code,
  m.rain_station_name,
  m.hydro_station_code,
  m.hydro_station_name
FROM geo_gqp_jbxx j
LEFT JOIN ai_slope_hydro_station_map m ON UPPER(m.gqpbh) = UPPER(j.GQPBH)
{where}
FETCH FIRST 80 ROWS ONLY
"""), params).mappings().all()
    return [dict(row) for row in rows if row.get("longitude") and row.get("latitude")]


def fetch_qweather_for_target(target: dict[str, Any]) -> list[dict[str, Any]]:
    if not QWEATHER_API_KEY:
        return []
    location = f"{target['longitude']},{target['latitude']}"
    common = {"location": location, "key": QWEATHER_API_KEY, "lang": "zh"}
    now = fetch_json(f"{QWEATHER_BASE_URL}/v7/weather/now", params=common)
    hourly = fetch_json(f"{QWEATHER_BASE_URL}/v7/weather/24h", params=common)
    warning = fetch_json(f"{QWEATHER_BASE_URL}/v7/warning/now", params=common)

    hourly_rows = hourly.get("hourly") or []
    rain_24h = sum(_to_float(row.get("precip")) for row in hourly_rows[:24])
    rain_3h = sum(_to_float(row.get("precip")) for row in hourly_rows[:3])
    now_data = now.get("now") or {}
    warnings = warning.get("warning") or []
    warning_text = "、".join(filter(None, [item.get("title") or item.get("typeName") for item in warnings[:3]]))
    obs_time = now_data.get("obsTime") or now.get("updateTime") or datetime.now().isoformat()

    return [{
        "gqpbh": target.get("gqpbh", ""),
        "county": target.get("county", ""),
        "township": target.get("township", ""),
        "station_code": target.get("rain_station_code") or f"QWEATHER:{location}",
        "station_name": target.get("rain_station_name") or "和风天气格点",
        "longitude": target.get("longitude"),
        "latitude": target.get("latitude"),
        "observation_time": obs_time,
        "rain_1h_mm": _to_float(now_data.get("precip")),
        "rain_3h_mm": rain_3h,
        "rain_24h_mm": rain_24h,
        "rain_72h_mm": None,
        "warning_level": warning_text or "",
        "data_source": "qweather",
        "raw_payload": json.dumps({"now": now, "hourly": hourly, "warning": warning}, ensure_ascii=False),
    }]


def fetch_open_meteo_for_target(target: dict[str, Any]) -> list[dict[str, Any]]:
    latitude = target.get("latitude")
    longitude = target.get("longitude")
    if latitude is None or longitude is None:
        return []
    payload = fetch_json(
        f"{OPEN_METEO_BASE_URL}/v1/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "precipitation",
            "past_days": 3,
            "forecast_days": 1,
            "timezone": "Asia/Shanghai",
        },
    )
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    precip = hourly.get("precipitation") or []
    pairs = []
    now = datetime.now()
    for time_text, value in zip(times, precip):
        try:
            observed_at = datetime.fromisoformat(str(time_text))
        except ValueError:
            continue
        if observed_at <= now:
            pairs.append((observed_at, _to_float(value)))
    if not pairs:
        return []
    pairs.sort(key=lambda item: item[0], reverse=True)
    obs_time = pairs[0][0].isoformat(sep=" ", timespec="seconds")
    rain_1h = _sum_recent_precip(pairs, 1)
    rain_3h = _sum_recent_precip(pairs, 3)
    rain_24h = _sum_recent_precip(pairs, 24)
    rain_72h = _sum_recent_precip(pairs, 72)
    location = f"{latitude},{longitude}"
    return [{
        "gqpbh": target.get("gqpbh", ""),
        "county": target.get("county", ""),
        "township": target.get("township", ""),
        "station_code": target.get("rain_station_code") or f"OPEN_METEO:{location}",
        "station_name": target.get("rain_station_name") or "Open-Meteo格点",
        "longitude": longitude,
        "latitude": latitude,
        "observation_time": obs_time,
        "rain_1h_mm": rain_1h,
        "rain_3h_mm": rain_3h,
        "rain_24h_mm": rain_24h,
        "rain_72h_mm": rain_72h,
        "warning_level": "",
        "data_source": "open_meteo",
        "raw_payload": json.dumps(payload, ensure_ascii=False),
    }]


def fetch_seniverse_for_target(target: dict[str, Any]) -> list[dict[str, Any]]:
    if not SENIVERSE_API_KEY:
        return []
    location = f"{target['latitude']}:{target['longitude']}"
    now = fetch_json(
        f"{SENIVERSE_BASE_URL}/v3/weather/now.json",
        params={"key": SENIVERSE_API_KEY, "location": location, "language": "zh-Hans", "unit": "c"},
    )
    hourly = fetch_json(
        f"{SENIVERSE_BASE_URL}/v3/weather/hourly.json",
        params={"key": SENIVERSE_API_KEY, "location": location, "language": "zh-Hans", "unit": "c", "start": 0, "hours": 24},
    )
    now_result = (now.get("results") or [{}])[0]
    hourly_result = (hourly.get("results") or [{}])[0]
    hourly_rows = hourly_result.get("hourly") or []
    rain_24h = sum(_to_float(row.get("precip")) for row in hourly_rows[:24])
    rain_3h = sum(_to_float(row.get("precip")) for row in hourly_rows[:3])
    return [{
        "gqpbh": target.get("gqpbh", ""),
        "county": target.get("county", ""),
        "township": target.get("township", ""),
        "station_code": target.get("rain_station_code") or f"SENIVERSE:{location}",
        "station_name": target.get("rain_station_name") or "心知天气格点",
        "longitude": target.get("longitude"),
        "latitude": target.get("latitude"),
        "observation_time": now_result.get("last_update") or datetime.now().isoformat(),
        "rain_1h_mm": None,
        "rain_3h_mm": rain_3h,
        "rain_24h_mm": rain_24h,
        "rain_72h_mm": None,
        "warning_level": "",
        "data_source": "seniverse",
        "raw_payload": json.dumps({"now": now, "hourly": hourly}, ensure_ascii=False),
    }]


def normalize_rainfall(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("records") if isinstance(payload, dict) else []
    normalized = []
    for item in records or []:
        normalized.append({
            "gqpbh": item.get("gqpbh", ""),
            "county": item.get("county", ""),
            "township": item.get("township", ""),
            "station_code": item.get("station_code", ""),
            "station_name": item.get("station_name", ""),
            "longitude": item.get("longitude"),
            "latitude": item.get("latitude"),
            "observation_time": item.get("observation_time"),
            "rain_1h_mm": item.get("rain_1h_mm"),
            "rain_3h_mm": item.get("rain_3h_mm"),
            "rain_24h_mm": item.get("rain_24h_mm"),
            "rain_72h_mm": item.get("rain_72h_mm"),
            "warning_level": item.get("warning_level", ""),
            "data_source": item.get("data_source", "external"),
            "raw_payload": json.dumps(item, ensure_ascii=False),
        })
    return normalized


def collect_rainfall(conn) -> list[dict[str, Any]]:
    if WEATHER_PROVIDER == "generic":
        return normalize_rainfall(fetch_json(RAIN_API_URL, RAIN_API_KEY))
    targets = get_targets(conn)
    records: list[dict[str, Any]] = []
    for target in targets:
        try:
            if WEATHER_PROVIDER == "open_meteo":
                records.extend(fetch_open_meteo_for_target(target))
            elif WEATHER_PROVIDER == "seniverse":
                records.extend(fetch_seniverse_for_target(target))
            elif WEATHER_PROVIDER == "qweather":
                records.extend(fetch_qweather_for_target(target))
        except Exception as exc:
            print(f"rainfall skip {target.get('gqpbh')}: {exc}")
    return records


def collect_cjh_water_level() -> list[dict[str, Any]]:
    html = fetch_text(CJH_WATER_URL)
    script_match = re.search(r"var\s+sssq\s*=\s*(\[.*?\]);", html, re.DOTALL)
    if script_match:
        payload = json.loads(script_match.group(1))
        return [_cjh_payload_to_record(item) for item in payload if item.get("stnm") and item.get("z")]

    parser = SimpleTableParser()
    parser.feed(html)
    records = []
    for row in parser.rows:
        if len(row) < 3 or "站名" in row[0]:
            continue
        station_name = row[0].strip()
        observation_time = _parse_cjh_time(row[1] if len(row) > 1 else "")
        level = _first_number(row[2] if len(row) > 2 else "")
        flow = _first_number(row[3] if len(row) > 3 else "")
        change = _first_number(row[4] if len(row) > 4 else "")
        if not station_name or level is None:
            continue
        records.append({
            "gqpbh": "",
            "county": "",
            "station_code": station_name,
            "station_name": station_name,
            "river_name": "长江流域",
            "longitude": None,
            "latitude": None,
            "observation_time": observation_time,
            "water_level_m": level,
            "change_24h_m": change,
            "change_72h_m": None,
            "flow_m3s": flow,
            "warning_level_m": None,
            "data_source": "cjh_public",
            "raw_payload": json.dumps({"row": row, "url": CJH_WATER_URL}, ensure_ascii=False),
        })
    return records


def _cjh_payload_to_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "gqpbh": "",
        "county": "",
        "station_code": item.get("stcd") or item.get("stnm") or "",
        "station_name": item.get("stnm") or "",
        "river_name": item.get("rvnm") or "长江流域",
        "longitude": None,
        "latitude": None,
        "observation_time": _parse_epoch_ms(item.get("tm")),
        "water_level_m": _to_float(item.get("z")),
        "change_24h_m": None,
        "change_72h_m": None,
        "flow_m3s": _to_float(item.get("q")),
        "warning_level_m": None,
        "data_source": "cjh_public",
        "raw_payload": json.dumps(item, ensure_ascii=False),
    }


def normalize_water_level(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("records") if isinstance(payload, dict) else []
    normalized = []
    for item in records or []:
        normalized.append({
            "gqpbh": item.get("gqpbh", ""),
            "county": item.get("county", ""),
            "station_code": item.get("station_code", ""),
            "station_name": item.get("station_name", ""),
            "river_name": item.get("river_name", ""),
            "longitude": item.get("longitude"),
            "latitude": item.get("latitude"),
            "observation_time": item.get("observation_time"),
            "water_level_m": item.get("water_level_m"),
            "change_24h_m": item.get("change_24h_m"),
            "change_72h_m": item.get("change_72h_m"),
            "flow_m3s": item.get("flow_m3s"),
            "warning_level_m": item.get("warning_level_m"),
            "data_source": item.get("data_source", "external"),
            "raw_payload": json.dumps(item, ensure_ascii=False),
        })
    return normalized


def collect_water_level() -> list[dict[str, Any]]:
    if WATER_PROVIDER == "generic":
        return normalize_water_level(fetch_json(WATER_LEVEL_API_URL, WATER_LEVEL_API_KEY))
    if WATER_PROVIDER == "cjh_public":
        try:
            return collect_cjh_water_level()
        except Exception as exc:
            print(f"water level skip cjh_public: {exc}")
    return []


def insert_rainfall(conn, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    sql = text("""
INSERT INTO ai_weather_rainfall_cache (
  gqpbh, county, township, station_code, station_name, longitude, latitude,
  observation_time, rain_1h_mm, rain_3h_mm, rain_24h_mm, rain_72h_mm,
  warning_level, data_source, raw_payload, fetched_at
) VALUES (
  :gqpbh, :county, :township, :station_code, :station_name, :longitude, :latitude,
  :observation_time, :rain_1h_mm, :rain_3h_mm, :rain_24h_mm, :rain_72h_mm,
  :warning_level, :data_source, :raw_payload, :fetched_at
)
""")
    for record in records:
        conn.execute(sql, {**record, "fetched_at": datetime.now()})


def insert_water_level(conn, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    sql = text("""
INSERT INTO ai_hydro_water_level_cache (
  gqpbh, county, station_code, station_name, river_name, longitude, latitude,
  observation_time, water_level_m, change_24h_m, change_72h_m, flow_m3s,
  warning_level_m, data_source, raw_payload, fetched_at
) VALUES (
  :gqpbh, :county, :station_code, :station_name, :river_name, :longitude, :latitude,
  :observation_time, :water_level_m, :change_24h_m, :change_72h_m, :flow_m3s,
  :warning_level_m, :data_source, :raw_payload, :fetched_at
)
""")
    for record in records:
        conn.execute(sql, {**record, "fetched_at": datetime.now()})


def _parse_cjh_time(text_value: str) -> str:
    text_value = (text_value or "").strip()
    year = datetime.now().year
    match = re.search(r"(\d{1,2})日\s*(\d{1,2})时", text_value)
    if match:
        return f"{year}-{datetime.now().month:02d}-{int(match.group(1)):02d} {int(match.group(2)):02d}:00:00"
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _parse_epoch_ms(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value) / 1000).isoformat(sep=" ", timespec="seconds")
    except Exception:
        return datetime.now().isoformat(sep=" ", timespec="seconds")


def _first_number(text_value: str) -> float | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(text_value or ""))
    return float(match.group(0)) if match else None


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _sum_recent_precip(pairs: list[tuple[datetime, float]], hours: int) -> float:
    return round(sum(value for _, value in pairs[:hours]), 2)


def main() -> None:
    engine = get_sqlalchemy_engine()
    try:
        with engine.begin() as conn:
            rainfall_records = collect_rainfall(conn)
            water_records = collect_water_level()
            insert_rainfall(conn, rainfall_records)
            insert_water_level(conn, water_records)
    finally:
        engine.dispose()
    print(f"provider weather={WEATHER_PROVIDER} water={WATER_PROVIDER} rainfall={len(rainfall_records)} water_level={len(water_records)}")


if __name__ == "__main__":
    main()
