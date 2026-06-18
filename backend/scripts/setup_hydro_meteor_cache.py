"""Create middle-cache tables for rainfall and water-level data.

Run from backend directory:
    python scripts/setup_hydro_meteor_cache.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import get_sqlalchemy_engine  # noqa: E402


TABLES = {
    "ai_weather_rainfall_cache": """
CREATE TABLE ai_weather_rainfall_cache (
  id BIGINT IDENTITY(1,1) PRIMARY KEY,
  gqpbh VARCHAR(64),
  county VARCHAR(64),
  township VARCHAR(128),
  station_code VARCHAR(128),
  station_name VARCHAR(200),
  longitude DECIMAL(12,6),
  latitude DECIMAL(12,6),
  observation_time TIMESTAMP,
  rain_1h_mm DECIMAL(10,2),
  rain_3h_mm DECIMAL(10,2),
  rain_24h_mm DECIMAL(10,2),
  rain_72h_mm DECIMAL(10,2),
  warning_level VARCHAR(64),
  data_source VARCHAR(128),
  raw_payload CLOB,
  fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""",
    "ai_hydro_water_level_cache": """
CREATE TABLE ai_hydro_water_level_cache (
  id BIGINT IDENTITY(1,1) PRIMARY KEY,
  gqpbh VARCHAR(64),
  county VARCHAR(64),
  station_code VARCHAR(128),
  station_name VARCHAR(200),
  river_name VARCHAR(200),
  longitude DECIMAL(12,6),
  latitude DECIMAL(12,6),
  observation_time TIMESTAMP,
  water_level_m DECIMAL(10,3),
  change_24h_m DECIMAL(10,3),
  change_72h_m DECIMAL(10,3),
  flow_m3s DECIMAL(14,2),
  warning_level_m DECIMAL(10,3),
  data_source VARCHAR(128),
  raw_payload CLOB,
  fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""",
    "ai_slope_hydro_station_map": """
CREATE TABLE ai_slope_hydro_station_map (
  id BIGINT IDENTITY(1,1) PRIMARY KEY,
  gqpbh VARCHAR(64),
  county VARCHAR(64),
  rain_station_code VARCHAR(128),
  rain_station_name VARCHAR(200),
  hydro_station_code VARCHAR(128),
  hydro_station_name VARCHAR(200),
  distance_km DECIMAL(10,3),
  priority INTEGER DEFAULT 1,
  remark VARCHAR(500),
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""",
    "ai_hydro_meteor_daily_cache": """
CREATE TABLE ai_hydro_meteor_daily_cache (
  id BIGINT IDENTITY(1,1) PRIMARY KEY,
  gqpbh VARCHAR(64),
  county VARCHAR(64),
  township VARCHAR(128),
  longitude DECIMAL(12,6),
  latitude DECIMAL(12,6),
  data_date DATE,
  rain_mm DECIMAL(10,2),
  rain_source VARCHAR(128),
  hydro_station_code VARCHAR(128),
  hydro_station_name VARCHAR(200),
  river_name VARCHAR(200),
  water_level_m DECIMAL(10,3),
  water_level_change_m DECIMAL(10,3),
  flow_m3s DECIMAL(14,2),
  water_source VARCHAR(128),
  raw_payload CLOB,
  fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""",
}


def table_exists(conn, table_name: str) -> bool:
    row = conn.execute(text("""
SELECT COUNT(*) AS count_value
FROM user_tables
WHERE table_name = UPPER(:table_name)
"""), {"table_name": table_name}).mappings().first()
    return bool(row and int(row["count_value"] or 0) > 0)


def main() -> None:
    engine = get_sqlalchemy_engine()
    try:
        with engine.begin() as conn:
            for table_name, ddl in TABLES.items():
                if table_exists(conn, table_name):
                    print(f"exists: {table_name}")
                    continue
                conn.execute(text(ddl))
                print(f"created: {table_name}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
