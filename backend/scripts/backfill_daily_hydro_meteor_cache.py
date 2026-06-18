"""Backfill daily rainfall and water-level cache for cross analysis.

Demo rainfall source:
  Open-Meteo Historical Weather API, no API key required.

Water-level note:
  Public CJH realtime data does not provide a full historical API here. This
  script aggregates available cached water-level observations by day. For a
  complete 2025-now water-level series, replace this part with an authorized
  hydrology interface or imported daily exchange file.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import get_sqlalchemy_engine  # noqa: E402


OPEN_METEO_ARCHIVE_URL = os.getenv("OPEN_METEO_ARCHIVE_URL", "https://archive-api.open-meteo.com/v1/archive").strip()
START_DATE = os.getenv("HYDRO_DAILY_START_DATE", "2025-01-01").strip()
END_DATE = os.getenv("HYDRO_DAILY_END_DATE", date.today().isoformat()).strip()
HYDRO_METEOR_TARGETS = [x.strip().upper() for x in os.getenv("HYDRO_METEOR_TARGETS", "").split(",") if x.strip()]
TARGET_LIMIT = int(os.getenv("HYDRO_DAILY_TARGET_LIMIT", "80"))


def fetch_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(url, params=params, headers={"User-Agent": "gqp-daily-hydro-meteor-backfill/1.0"}, timeout=40)
    response.raise_for_status()
    return response.json()


def get_targets(conn) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit_value": TARGET_LIMIT}
    where = ""
    if HYDRO_METEOR_TARGETS:
        placeholders = []
        for index, code in enumerate(HYDRO_METEOR_TARGETS):
            key = f"code_{index}"
            placeholders.append(f":{key}")
            params[key] = code
        where = f"WHERE UPPER(GQPBH) IN ({','.join(placeholders)})"
    rows = conn.execute(text(f"""
SELECT GQPBH AS gqpbh, GQPMC AS gqpmc, SSQX AS county, SSJD AS township, X AS longitude, Y AS latitude
FROM geo_gqp_jbxx
{where}
FETCH FIRST :limit_value ROWS ONLY
"""), params).mappings().all()
    return [dict(row) for row in rows if row.get("longitude") and row.get("latitude")]


def fetch_open_meteo_daily(target: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = fetch_json(
        OPEN_METEO_ARCHIVE_URL,
        {
            "latitude": target["latitude"],
            "longitude": target["longitude"],
            "start_date": START_DATE,
            "end_date": END_DATE,
            "daily": "precipitation_sum",
            "timezone": "Asia/Shanghai",
        },
    )
    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    rains = daily.get("precipitation_sum") or []
    records = []
    for data_date, rain in zip(times, rains):
        records.append({
            "gqpbh": target.get("gqpbh", ""),
            "county": target.get("county", ""),
            "township": target.get("township", ""),
            "longitude": target.get("longitude"),
            "latitude": target.get("latitude"),
            "data_date": data_date,
            "rain_mm": _to_float(rain),
            "rain_source": "open_meteo_archive",
            "hydro_station_code": "",
            "hydro_station_name": "",
            "river_name": "",
            "water_level_m": None,
            "water_level_change_m": None,
            "flow_m3s": None,
            "water_source": "",
            "raw_payload": "",
        })
    return records, payload


def delete_existing_rain(conn, gqpbh: str) -> None:
    conn.execute(text("""
DELETE FROM ai_hydro_meteor_daily_cache
WHERE UPPER(gqpbh) = UPPER(:gqpbh)
  AND data_date >= :start_date
  AND data_date <= :end_date
  AND rain_source = 'open_meteo_archive'
"""), {"gqpbh": gqpbh, "start_date": START_DATE, "end_date": END_DATE})


def insert_daily_records(conn, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    sql = text("""
INSERT INTO ai_hydro_meteor_daily_cache (
  gqpbh, county, township, longitude, latitude, data_date,
  rain_mm, rain_source, hydro_station_code, hydro_station_name, river_name,
  water_level_m, water_level_change_m, flow_m3s, water_source, raw_payload, fetched_at
) VALUES (
  :gqpbh, :county, :township, :longitude, :latitude, :data_date,
  :rain_mm, :rain_source, :hydro_station_code, :hydro_station_name, :river_name,
  :water_level_m, :water_level_change_m, :flow_m3s, :water_source, :raw_payload, :fetched_at
)
""")
    now = datetime.now()
    for record in records:
        conn.execute(sql, {**record, "fetched_at": now})


def aggregate_cached_water_level(conn) -> int:
    conn.execute(text("""
DELETE FROM ai_hydro_meteor_daily_cache
WHERE data_date >= :start_date
  AND data_date <= :end_date
  AND water_source = 'cjh_public_daily_aggregate'
  AND (gqpbh IS NULL OR gqpbh = '')
"""), {"start_date": START_DATE, "end_date": END_DATE})
    rows = conn.execute(text("""
SELECT
  CAST(observation_time AS DATE) AS data_date,
  station_code,
  station_name,
  river_name,
  AVG(water_level_m) AS water_level_m,
  AVG(flow_m3s) AS flow_m3s
FROM ai_hydro_water_level_cache
WHERE observation_time IS NOT NULL
  AND CAST(observation_time AS DATE) >= :start_date
  AND CAST(observation_time AS DATE) <= :end_date
GROUP BY CAST(observation_time AS DATE), station_code, station_name, river_name
"""), {"start_date": START_DATE, "end_date": END_DATE}).mappings().all()
    records = []
    for row in rows:
        records.append({
            "gqpbh": "",
            "county": "",
            "township": "",
            "longitude": None,
            "latitude": None,
            "data_date": row["data_date"],
            "rain_mm": None,
            "rain_source": "",
            "hydro_station_code": row["station_code"] or "",
            "hydro_station_name": row["station_name"] or "",
            "river_name": row["river_name"] or "",
            "water_level_m": row["water_level_m"],
            "water_level_change_m": None,
            "flow_m3s": row["flow_m3s"],
            "water_source": "cjh_public_daily_aggregate",
            "raw_payload": "",
        })
    insert_daily_records(conn, records)
    return len(records)


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def main() -> None:
    engine = get_sqlalchemy_engine()
    rainfall_total = 0
    water_total = 0
    try:
        with engine.begin() as conn:
            targets = get_targets(conn)
            for target in targets:
                try:
                    records, payload = fetch_open_meteo_daily(target)
                    for record in records:
                        record["raw_payload"] = json.dumps({
                            "source": "open_meteo_archive",
                            "latitude": target.get("latitude"),
                            "longitude": target.get("longitude"),
                            "generationtime_ms": payload.get("generationtime_ms"),
                        }, ensure_ascii=False)
                    delete_existing_rain(conn, str(target.get("gqpbh") or ""))
                    insert_daily_records(conn, records)
                    rainfall_total += len(records)
                except Exception as exc:
                    print(f"rain daily skip {target.get('gqpbh')}: {exc}")
            water_total = aggregate_cached_water_level(conn)
    finally:
        engine.dispose()
    print(f"daily_rainfall={rainfall_total} daily_water={water_total} start={START_DATE} end={END_DATE}")


if __name__ == "__main__":
    main()
