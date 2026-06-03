from __future__ import annotations

import json
import re
from decimal import Decimal
from html import escape
from pathlib import Path
from urllib.parse import quote_plus

import numpy as np
from sqlalchemy import create_engine, text

from app.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER
from app.slope_object_index import clean_card_text, enrich_slope_cards
from app.sqlserver_db import query_sqlserver_for_display


ASSET_ROOT = Path(__file__).resolve().parents[1] / "generated" / "displacement_dashboard"
ASSET_URL_ROOT = "/report-assets/displacement_dashboard"
REPORT_DIGITIZED_ROOT = Path(__file__).resolve().parents[1] / "generated" / "report_digitized_charts"
MONITOR_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "generated" / "professional_monitor_registry" / "registry.json"
NAME_LOOKUP_CACHE: dict[tuple[str, str, str], str] = {}
DISPLACEMENT_TEST_START = "2025-01-01"
DISPLACEMENT_TEST_END = "2025-12-31"
DISPLACEMENT_ALERT_THRESHOLD_MM = 4.5


def _to_float(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except Exception:
        return 0.0


def _to_str(value) -> str:
    return "" if value is None else str(value)


def _engine():
    password = quote_plus(DM_PASSWORD)
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def get_recent_displacement_dashboard(limit: int = 4) -> dict:
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    engine = _engine()
    try:
        with engine.connect() as conn:
            report_basis = _fetch_latest_report_basis(conn)
            professional_slope_count = _fetch_professional_slope_count(conn)
            basis_by_county = {item["county"]: item for item in report_basis if item.get("county")}
            basis_counties = [item["county"] for item in report_basis if item.get("county")]
            matched_slopes = _fetch_top_slopes(conn, max(limit * 6, 36), basis_counties)
            candidates = _fetch_top_slopes(conn, max(limit * 4, 24))
            slopes = matched_slopes or candidates
            cards = []
            for slope in slopes:
                if len(cards) >= limit:
                    break
                points = _fetch_slope_points(conn, slope["gqpbh"])
                series = _fetch_slope_series(conn, slope["gqpbh"], [item["jcdbh"] for item in points])
                stability = _build_stability(slope, points, series)
                chart_paths = _write_point_chart(slope, points, series, stability)
                basis = basis_by_county.get(slope.get("ssqx"), _fallback_basis(slope.get("ssqx", "")))
                slope["freshness_note"] = _build_freshness_note(slope, basis)
                cards.append({
                    **slope,
                    "report_basis": basis,
                    "points": points,
                    "stability": stability,
                    "chart_url": chart_paths["html_url"],
                    "data_url": chart_paths["json_url"],
                    "chart_svg": chart_paths.get("svg", ""),
                })
            _attach_qmqf_photos(cards)
            _attach_sqlserver_contacts(cards)
            enrich_slope_cards(cards)
    finally:
        engine.dispose()

    return {
        "status": "success",
        "title": "近期专业监测情况",
        "description": "依据2025年月报专业监测成果表，按同一监测点各月X/Y/H本期位移变化量带正负累计；累计变化量相对较大的对象纳入展示，并给出月度平均变化速率。",
        "professional_slope_count": professional_slope_count,
        "basis_rule": "",
        "report_basis": report_basis,
        "items": cards,
    }


def _fetch_latest_report_basis(conn) -> list[dict]:
    sql = text("""
WITH latest_doc AS (
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
    AND d.report_year IS NOT NULL
    AND d.report_month IS NOT NULL
    AND d.county IS NOT NULL
    AND d.county <> ''
),
latest_chunk AS (
  SELECT
    d.county,
    d.report_year,
    d.report_month,
    d.report_type,
    d.file_name,
    d.key_points,
    d.mentioned_slopes,
    c.content,
    ROW_NUMBER() OVER (
      PARTITION BY d.file_hash
      ORDER BY
        CASE
          WHEN c.content LIKE '%位移%' OR c.content LIKE '%变形%' OR c.content LIKE '%稳定%' OR c.content LIKE '%监测点%' THEN 0
          ELSE 1
        END,
        c.chunk_index ASC
    ) AS chunk_rank
  FROM latest_doc d
  LEFT JOIN ai_monthly_report_chunk c ON c.file_hash = d.file_hash
  WHERE d.rn = 1
)
SELECT
  county,
  report_year,
  report_month,
  report_type,
  file_name,
  SUBSTR(key_points, 1, 260) AS key_points,
  SUBSTR(mentioned_slopes, 1, 220) AS mentioned_slopes,
  SUBSTR(content, 1, 280) AS excerpt
FROM latest_chunk
WHERE chunk_rank = 1
ORDER BY county ASC
""")
    rows = conn.execute(sql).mappings().all()
    return [
        {
            "county": _to_str(row["county"]),
            "year": int(row["report_year"] or 0),
            "month": int(row["report_month"] or 0),
            "report_type": _to_str(row["report_type"]) or "月报",
            "file_name": _to_str(row["file_name"]),
            "key_points": _to_str(row["key_points"]),
            "mentioned_slopes": _to_str(row["mentioned_slopes"]),
            "excerpt": _to_str(row["excerpt"]),
            "rule": "优先采用该区县最晚月份月报作为结论主依据。",
        }
        for row in rows
    ]


def _fetch_professional_slope_count(conn) -> int:
    sql = text("""
SELECT COUNT(DISTINCT m.gqpbh) AS count_value
FROM ai_professional_monitor_monthly_value m
WHERE m.report_year = 2025
  AND m.gqpbh IS NOT NULL
  AND m.gqpbh <> ''
  AND m.monitor_point IS NOT NULL
  AND m.monitor_point <> ''
  AND m.monitor_point NOT LIKE 'KZ%'
""")
    row = conn.execute(sql).mappings().first()
    return int(row["count_value"] or 0) if row else 0


def _fallback_basis(county: str) -> dict:
    return {
        "county": county,
        "year": 0,
        "month": 0,
        "report_type": "",
        "file_name": "",
        "key_points": "",
        "mentioned_slopes": "",
        "excerpt": "",
        "rule": "未匹配到该区县月报，当前结果仅作为位移库补充项。",
    }


def _load_report_digitized_cards(limit: int, basis_by_county: dict[str, dict]) -> list[dict]:
    registry_cards = _load_registry_cards(limit, basis_by_county)
    if registry_cards:
        return registry_cards

    cards: list[dict] = []
    if not REPORT_DIGITIZED_ROOT.exists():
        return cards

    for json_path in REPORT_DIGITIZED_ROOT.glob("*/*_digitized.json"):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        card = _build_report_digitized_card(data, json_path, basis_by_county)
        if card:
            cards.append(card)

    cards.sort(key=lambda item: (item.get("latest_monitor_date", ""), item.get("max_recent_change", 0)), reverse=True)
    return cards[:limit]


def _load_registry_cards(limit: int, basis_by_county: dict[str, dict]) -> list[dict]:
    if not MONITOR_REGISTRY_PATH.exists():
        return []
    try:
        payload = json.loads(MONITOR_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = payload.get("items") or []
    cards = []
    for item in items:
        card = _build_registry_card(item, basis_by_county)
        if card:
            cards.append(card)
    cards = _merge_registry_cards_by_slope(cards)
    resolved_cards = [card for card in cards if not _is_unresolved_chart(card)]
    if len(resolved_cards) >= limit:
        cards = resolved_cards
    cards.sort(
        key=lambda row: (
            not _is_unresolved_chart(row),
            row.get("latest_monitor_date", ""),
            row.get("max_recent_change", 0),
        ),
        reverse=True,
    )
    grouped: dict[str, list[dict]] = {}
    for card in cards:
        grouped.setdefault(card.get("ssqx") or "未标注区县", []).append(card)

    selected: list[dict] = []
    per_county = max(1, min(2, int(np.ceil(limit / max(1, len(grouped))))))
    for county in sorted(grouped):
        selected.extend(grouped[county][:per_county])
    if len(selected) < limit:
        selected_keys = {(item["ssqx"], item["gqpbh"]) for item in selected}
        for card in cards:
            key = (card["ssqx"], card["gqpbh"])
            if key not in selected_keys:
                selected.append(card)
                selected_keys.add(key)
            if len(selected) >= limit:
                break
    return selected[:limit]


def _enrich_cards_with_report_relation(conn, cards: list[dict]) -> None:
    for card in cards:
        relation_points = _fetch_report_relation_points(
            conn,
            _to_str(card.get("ssqx")),
            _to_str(card.get("gqpbh")),
            _to_str(card.get("gqpmc")),
        )
        if not relation_points:
            continue
        existing = {_to_str(point.get("jcdbh")).upper(): point for point in card.get("points") or []}
        for relation_point in relation_points:
            point_name = _to_str(relation_point.get("monitor_point"))
            key = point_name.upper()
            has_values = bool(relation_point.get("has_values"))
            point_payload = {
                "jcdbh": point_name,
                "record_count": 1 if has_values else 0,
                "x_change": _to_float(relation_point.get("cumulative_x")) if has_values else None,
                "y_change": _to_float(relation_point.get("cumulative_y")) if has_values else None,
                "h_change": _to_float(relation_point.get("cumulative_h")) if has_values else None,
                "current_x": _to_float(relation_point.get("current_x")) if has_values else None,
                "current_y": _to_float(relation_point.get("current_y")) if has_values else None,
                "current_h": _to_float(relation_point.get("current_h")) if has_values else None,
                "max_recent_change": max(
                    abs(_to_float(relation_point.get("cumulative_x"))),
                    abs(_to_float(relation_point.get("cumulative_y"))),
                    abs(_to_float(relation_point.get("cumulative_h"))),
                ),
            }
            if key not in existing:
                existing[key] = point_payload
            elif relation_point.get("has_values"):
                existing[key].update(point_payload)
        points = list(existing.values())
        points.sort(key=lambda row: (_to_float(row.get("max_recent_change")), _to_str(row.get("jcdbh"))), reverse=True)
        card["points"] = points
        card["point_count"] = len(points)


def _fetch_report_relation_points(conn, county: str, gqpbh: str, gqpmc: str) -> list[dict]:
    if not gqpbh and not gqpmc:
        return []
    params = {"county": county}
    base_filters = []
    if county:
        base_filters.append("county = :county")
    if gqpbh:
        params["gqpbh"] = gqpbh.upper()
        rows = _query_report_relation_points(conn, " AND ".join(base_filters + ["UPPER(gqpbh) = :gqpbh"]), params)
        if any(row.get("has_values") for row in rows):
            return rows
    if gqpmc:
        params["gqpmc"] = gqpmc
        rows = _query_report_relation_points(conn, " AND ".join(base_filters + ["gqpmc = :gqpmc"]), params)
        if rows:
            return rows
    if gqpbh:
        return _query_report_relation_points(conn, " AND ".join(base_filters + ["UPPER(gqpbh) = :gqpbh"]), params)
    return []


def _query_report_relation_points(conn, where_clause: str, params: dict) -> list[dict]:
    if not where_clause:
        return []
    sql = text(f"""
SELECT *
FROM (
  SELECT
    monitor_point,
    current_x,
    cumulative_x,
    current_y,
    cumulative_y,
    current_h,
    cumulative_h,
    CASE
      WHEN cumulative_x IS NOT NULL OR cumulative_y IS NOT NULL OR cumulative_h IS NOT NULL THEN 1
      ELSE 0
    END AS has_values,
    ROW_NUMBER() OVER (
      PARTITION BY monitor_point
      ORDER BY
        CASE WHEN cumulative_x IS NOT NULL OR cumulative_y IS NOT NULL OR cumulative_h IS NOT NULL THEN 0 ELSE 1 END,
        report_year DESC NULLS LAST,
        report_month DESC NULLS LAST
    ) AS rn
  FROM ai_professional_monitor_monthly_value
  WHERE {where_clause}
    AND monitor_point IS NOT NULL
    AND monitor_point <> ''
    AND monitor_point NOT LIKE 'KZ%'
)
WHERE rn = 1
ORDER BY monitor_point
""")
    try:
        rows = conn.execute(sql, params).mappings().all()
    except Exception:
        return []
    return [dict(row) for row in rows if _to_str(row["monitor_point"])]


def _merge_registry_cards_by_slope(cards: list[dict]) -> list[dict]:
    merged: dict[tuple[str, str], dict] = {}
    for card in cards:
        key = (_to_str(card.get("ssqx")), _to_str(card.get("gqpbh")).upper())
        if not key[1]:
            continue
        existing = merged.get(key)
        if not existing:
            card["points"] = _dedupe_points(card.get("points") or [])
            card["point_count"] = len(card["points"]) or int(card.get("point_count") or 0)
            merged[key] = card
            continue

        combined_points = _dedupe_points((existing.get("points") or []) + (card.get("points") or []))
        existing["points"] = combined_points
        existing["point_count"] = len(combined_points)
        if _to_float(card.get("max_recent_change")) > _to_float(existing.get("max_recent_change")):
            keep_points = existing["points"]
            keep_count = existing["point_count"]
            card["points"] = keep_points
            card["point_count"] = keep_count
            merged[key] = card
            existing = card
        if _to_str(card.get("latest_monitor_date")) > _to_str(existing.get("latest_monitor_date")):
            existing["latest_monitor_date"] = card.get("latest_monitor_date")
    return list(merged.values())


def _dedupe_points(points: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()
    for point in points:
        key = _to_str(point.get("jcdbh")).upper()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(point)
    result.sort(key=lambda row: _to_float(row.get("max_recent_change")), reverse=True)
    return result


def _build_registry_card(item: dict, basis_by_county: dict[str, dict]) -> dict | None:
    data_path = Path(_to_str(item.get("digitized_json")))
    if not data_path.exists():
        return None
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    rows = _rows_from_report_series(data.get("series") or [])
    if not rows:
        return None
    county = _to_str(item.get("county"))
    gqpbh = _to_str(item.get("gqpbh")) or _safe_name(_to_str(item.get("chart_title")))
    gqpmc = _to_str(item.get("gqpmc")) or _to_str(item.get("chart_title")) or gqpbh
    top_point = _to_str(item.get("monitor_point")) or "监测点"
    gqpmc = _resolve_display_name(county, gqpbh, gqpmc, top_point, _to_str(item.get("chart_title")))
    latest_date = _to_str(item.get("latest_monitor_date")) or rows[-1]["date"]
    max_change = round(_to_float(item.get("latest_max_change")) or rows[-1]["max_change"], 2)
    slope = {
        "gqpbh": gqpbh,
        "gqpmc": gqpmc,
        "ssqx": county,
        "point_count": 1,
        "latest_monitor_date": latest_date,
        "max_recent_change": max_change,
        "chart_source": "report_registry",
        "value_mode": "本期位移" if data.get("digitize_method") == "monthly_report_table" else "累计位移",
    }
    points = [{
        "jcdbh": top_point,
        "record_count": len(rows),
        "x_change": rows[-1]["x"],
        "y_change": rows[-1]["y"],
        "h_change": rows[-1]["h"],
        "max_recent_change": rows[-1]["max_change"],
    }]
    basis = basis_by_county.get(county, _fallback_basis(county))
    stability = _build_report_stability(slope, top_point, rows)
    stability["report_evaluation"] = _extract_report_evaluation(basis)
    chart_paths = _write_report_digitized_chart(slope, top_point, rows, stability, data, data_path)
    return {
        **slope,
        "freshness_note": f"监测曲线更新至{latest_date}，建议结合现场巡查情况持续跟踪。",
        "report_basis": basis,
        "points": points,
        "stability": stability,
        "chart_url": chart_paths["html_url"],
        "data_url": chart_paths["json_url"],
        "chart_svg": chart_paths["svg"],
    }


def _is_unresolved_chart(row: dict) -> bool:
    name = _to_str(row.get("gqpmc"))
    code = _to_str(row.get("gqpbh"))
    point = _to_str(row.get("stability", {}).get("top_point"))
    return (name.startswith("第") and "专业监测曲线" in name) or code.startswith("第") or point.startswith("P")


def _resolve_display_name(county: str, gqpbh: str, gqpmc: str, monitor_point: str, title: str = "") -> str:
    if gqpmc and gqpmc != gqpbh and not gqpmc.startswith("第"):
        return gqpmc
    from_title = _extract_name_from_text(gqpbh, title)
    if from_title:
        return from_title
    cache_key = (county, gqpbh, monitor_point)
    if cache_key in NAME_LOOKUP_CACHE:
        return NAME_LOOKUP_CACHE[cache_key] or gqpmc
    found = _lookup_name_from_report_text(county, gqpbh, monitor_point)
    NAME_LOOKUP_CACHE[cache_key] = found
    return found or gqpmc or gqpbh


def _lookup_name_from_report_text(county: str, gqpbh: str, monitor_point: str) -> str:
    if not gqpbh and not monitor_point:
        return ""
    terms = [term for term in (gqpbh, monitor_point) if term and not term.startswith("P")]
    if not terms:
        return ""
    clauses = " OR ".join(f"content LIKE :term{idx}" for idx, _ in enumerate(terms))
    params = {f"term{idx}": f"%{term}%" for idx, term in enumerate(terms)}
    params["county"] = county
    sql = text(f"""
SELECT SUBSTR(content, 1, 2500) AS content
FROM ai_monthly_report_chunk
WHERE county = :county
  AND ({clauses})
ORDER BY report_year DESC NULLS LAST, report_month DESC NULLS LAST, chunk_index ASC
FETCH FIRST 8 ROWS ONLY
""")
    engine = _engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
    except Exception:
        rows = []
    finally:
        engine.dispose()
    for row in rows:
        text_value = _to_str(row.get("content"))
        name = _extract_name_from_text(gqpbh, text_value)
        if name:
            return name
        if monitor_point:
            name = _extract_name_near_monitor(monitor_point, text_value)
            if name:
                return name
    return ""


def _extract_name_from_text(gqpbh: str, text_value: str) -> str:
    if not gqpbh or not text_value:
        return ""
    code = re.escape(gqpbh)
    patterns = [
        rf"([\u4e00-\u9fa5A-Za-z0-9\-—、，,（）()#]+?高切坡)\s*[（(]\s*{code}\s*[）)]",
        rf"{code}\s*([\u4e00-\u9fa5A-Za-z0-9\-—、，,（）()#]+?高切坡)",
        rf"([\u4e00-\u9fa5A-Za-z0-9\-—、，,（）()#]{{2,40}}?)\s*[（(]\s*{code}\s*[）)]",
    ]
    for pattern in patterns:
        match = re.search(pattern, text_value)
        if match:
            name = _clean_slope_name(match.group(1), gqpbh)
            if name and name != gqpbh:
                return name
    return ""


def _extract_name_near_monitor(monitor_point: str, text_value: str) -> str:
    point = re.escape(monitor_point)
    patterns = [
        rf"([\u4e00-\u9fa5A-Za-z0-9\-—、，,（）()#]+?高切坡)[^。；;\n]{{0,80}}{point}",
        rf"{point}[^。；;\n]{{0,80}}([\u4e00-\u9fa5A-Za-z0-9\-—、，,（）()#]+?高切坡)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text_value)
        if match:
            name = _clean_slope_name(match.group(1), "")
            if name:
                return name
    return ""


def _clean_slope_name(raw_name: str, gqpbh: str = "") -> str:
    name = re.sub(r"^\d+[、.．]?", "", _to_str(raw_name)).strip(" ，,。；;（）()")
    name = re.sub(r"^(由于|其中|以及|分别为|为|和|与)", "", name).strip(" ，,。；;（）()")
    name = re.sub(r"^[，,、：:；;。]+", "", name).strip()
    if gqpbh:
        name = name.replace(gqpbh, "").strip(" ，,。；;（）()")
    blacklist = ("专业监测", "监测点", "累计位移", "本期位移", "报告", "图", "表")
    if not name or any(word == name for word in blacklist):
        return ""
    if len(name) > 42:
        name = name[-42:]
        name = re.sub(r"^[^\u4e00-\u9fa5]+", "", name)
    return name


def _build_report_digitized_card(data: dict, json_path: Path, basis_by_county: dict[str, dict]) -> dict | None:
    series = data.get("series") or []
    if len(series) < 2:
        return None

    title = _to_str(data.get("title")) or json_path.stem
    code_match = re.search(r"（([A-Z]{1,5}\d+[A-Z0-9*]*)）", title)
    monitor_match = re.match(r"([A-Za-z]{1,8}\d+)", title)
    name_match = re.search(r"（([^（）]+高切坡[^（）]*)（", title)

    gqpbh = code_match.group(1) if code_match else _safe_name(title)
    top_point = monitor_match.group(1) if monitor_match else "月报图表"
    gqpmc = name_match.group(1) if name_match else title
    county = _infer_county_from_report_path(json_path, basis_by_county)
    rows = _rows_from_report_series(series)
    if not rows:
        return None

    latest_date = rows[-1]["date"]
    points = [{
        "jcdbh": top_point,
        "record_count": len(rows),
        "x_change": rows[-1]["x"],
        "y_change": rows[-1]["y"],
        "h_change": rows[-1]["h"],
        "max_recent_change": rows[-1]["max_change"],
    }]
    slope = {
        "gqpbh": gqpbh,
        "gqpmc": gqpmc,
        "ssqx": county,
        "point_count": 1,
        "latest_monitor_date": latest_date,
        "max_recent_change": rows[-1]["max_change"],
        "chart_source": "report_digitized",
    }
    basis = basis_by_county.get(county, _fallback_basis(county))
    stability = _build_report_stability(slope, top_point, rows)
    stability["report_evaluation"] = _extract_report_evaluation(basis)
    chart_paths = _write_report_digitized_chart(slope, top_point, rows, stability, data, json_path)
    return {
        **slope,
        "freshness_note": f"监测曲线更新至{latest_date}，建议结合现场巡查情况持续跟踪。",
        "report_basis": basis,
        "points": points,
        "stability": stability,
        "chart_url": chart_paths["html_url"],
        "data_url": chart_paths["json_url"],
        "chart_svg": chart_paths["svg"],
    }


def _infer_county_from_report_path(json_path: Path, basis_by_county: dict[str, dict]) -> str:
    folder = json_path.parent.name.lower()
    county_map = {
        "xingshan": "兴山县",
        "yiling": "夷陵区",
        "badong": "巴东县",
        "zigui": "秭归县",
    }
    for key, county in county_map.items():
        if key in folder:
            return county
    return next(iter(basis_by_county.keys()), "")


def _rows_from_report_series(series: list[dict]) -> list[dict]:
    dates = [item.get("date") for item in (series[0].get("data") or [])]
    value_by_name = []
    for item in series[:3]:
        value_by_name.append([_to_float(point.get("value")) for point in (item.get("data") or [])])
    while len(value_by_name) < 3:
        value_by_name.append([0.0] * len(dates))

    rows = []
    for index, date in enumerate(dates):
        if not date:
            continue
        x = value_by_name[0][index] if index < len(value_by_name[0]) else 0.0
        y = value_by_name[1][index] if index < len(value_by_name[1]) else 0.0
        h = value_by_name[2][index] if index < len(value_by_name[2]) else 0.0
        rows.append({
            "date": _to_str(date),
            "x": round(x, 2),
            "y": round(y, 2),
            "h": round(h, 2),
            "max_change": round(max(abs(x), abs(y), abs(h)), 2),
        })
    return rows


def _build_report_stability(slope: dict, top_point: str, rows: list[dict]) -> dict:
    current = rows[-1]["max_change"]
    recent_values = [row["max_change"] for row in rows[-12:]]
    trend = _linear_slope(recent_values) if len(recent_values) >= 2 else 0.0
    next_1 = max(0.0, current + trend)
    next_3 = max(0.0, current + trend * 3)
    if current >= 50 or abs(trend) >= 1.5:
        level = "稳定性需重点复核"
        advice = "建议结合报告结论、现场巡查和最新监测原始数据复核，重点关注持续增大的方向。"
    elif current >= 20 or abs(trend) >= 0.8:
        level = "稳定性一般"
        advice = "建议保持月度跟踪，若连续增大则提高现场复核频次。"
    else:
        level = "总体较稳定"
        advice = "建议按既定频率持续监测，保留趋势跟踪。"
    return {
        "level": level,
        "top_point": top_point,
        "summary": f"{slope['gqpmc']}监测曲线中{top_point}{slope.get('value_mode', '累计位移')}变化量达到约{current:.1f}mm。",
        "prediction": f"按近12期趋势估算，未来1个月可能达到约{next_1:.1f}mm，未来3个月可能达到约{next_3:.1f}mm。",
        "advice": advice,
    }


def _extract_report_evaluation(basis: dict) -> str:
    source = "。".join(
        part for part in [
            _to_str(basis.get("key_points")),
            _to_str(basis.get("excerpt")),
        ]
        if part
    )
    if not source:
        return ""
    source = re.sub(r"[\[\]\"{}]", "", source)
    sentences = re.split(r"[。；;\n]", source)
    picked = []
    for sentence in sentences:
        sentence = sentence.strip(" ,，")
        if any(skip in sentence for skip in ("项目", "报告名称", "目录", "编制", "委托", "技术服务", "监测预警系统", "专业监测工程", "高切坡监测预警专业监测")):
            continue
        if 12 <= len(sentence) <= 120 and any(word in sentence for word in ("稳定", "变形", "异常", "建议", "风险", "预警", "裂缝")):
            picked.append(sentence)
        if len(picked) >= 2:
            break
    return "报告研判：" + "；".join(picked) + "。" if picked else ""


def _write_report_digitized_chart(
    slope: dict,
    top_point: str,
    rows: list[dict],
    stability: dict,
    source_data: dict,
    json_path: Path,
) -> dict:
    safe_name = f"report_{_safe_name(slope['gqpbh'])}_{_safe_name(top_point)}"
    data_path = ASSET_ROOT / f"{safe_name}.json"
    svg_path = ASSET_ROOT / f"{safe_name}.svg"
    data = {
        "slope": slope,
        "selected_point": top_point,
        "series": rows,
        "stability": stability,
        "report_chart": {
            "title": source_data.get("title", ""),
            "source_image_url": source_data.get("source_image_url", ""),
            "digitized_json": str(json_path),
            "method": source_data.get("digitize_method", ""),
        },
    }
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    svg = _build_svg_chart(slope, top_point, rows, stability)
    svg_path.write_text(svg, encoding="utf-8")
    return {
        "html_url": f"{ASSET_URL_ROOT}/{svg_path.name}",
        "json_url": f"{ASSET_URL_ROOT}/{data_path.name}",
        "svg": svg,
    }


def _build_freshness_note(slope: dict, basis: dict) -> str:
    latest = _to_str(slope.get("latest_monitor_date"))[:10]
    year = int(basis.get("year") or 0)
    if latest and year and latest[:4].isdigit() and int(latest[:4]) < year:
        return f"监测曲线更新至{latest}，晚于该日期的研判以月报结论为主。"
    if latest:
        return f"监测曲线更新至{latest}。"
    return "暂未读取到该坡监测曲线更新时间。"


def _fetch_top_slopes(conn, limit: int, counties: list[str] | None = None) -> list[dict]:
    county_filter = ""
    if counties:
        county_values = ", ".join("'" + county.replace("'", "''") + "'" for county in counties)
        county_filter = f"AND COALESCE(r.county, j.ssqx, '') IN ({county_values})"
    sql = text(f"""
WITH point_sum AS (
  SELECT
    MAX(county) AS county,
    gqpbh,
    MAX(gqpmc) AS gqpmc,
    monitor_point AS jcdbh,
    SUM(COALESCE(current_x, 0)) AS x_change,
    SUM(COALESCE(current_y, 0)) AS y_change,
    SUM(COALESCE(current_h, 0)) AS h_change,
    COUNT(DISTINCT report_month) AS record_count,
    MAX(report_month) AS latest_month
FROM ai_professional_monitor_monthly_value
  WHERE report_year = 2025
    AND report_month BETWEEN 1 AND 12
    AND gqpbh IS NOT NULL
    AND gqpbh <> ''
    AND monitor_point IS NOT NULL
    AND monitor_point <> ''
    AND monitor_point NOT LIKE 'KZ%'
    AND (current_x IS NOT NULL OR current_y IS NOT NULL OR current_h IS NOT NULL)
  GROUP BY gqpbh, monitor_point
),
ranked AS (
  SELECT
    gqpbh,
    jcdbh,
    county,
    gqpmc,
    latest_month,
    record_count,
    x_change,
    y_change,
    h_change,
    GREATEST(
      ABS(x_change),
      ABS(y_change),
      ABS(h_change)
    ) AS max_recent_change,
    GREATEST(ABS(x_change), ABS(y_change), ABS(h_change)) / 12 AS avg_monthly_rate
  FROM point_sum
)
SELECT
  r.gqpbh,
  COALESCE(j.gqpmc, r.gqpmc, r.gqpbh) AS gqpmc,
  COALESCE(j.ssqx, r.county, '') AS ssqx,
  COALESCE(
    NULLIF(MAX(j.zrdwfzr), ''),
    NULLIF(MAX(j.PTU_CONTACT), ''),
    NULLIF(MAX(j.DISTRICT_MANAGEMENT_STAFF), '')
  ) AS contact_name,
  COALESCE(
    NULLIF(MAX(j.zrdwfzrdh), ''),
    NULLIF(MAX(j.PTU_PHONE), '')
  ) AS contact_phone,
  COUNT(DISTINCT r.jcdbh) AS point_count,
  MAX(r.latest_month) AS latest_monitor_month,
  MAX(r.max_recent_change) AS max_recent_change,
  MAX(r.avg_monthly_rate) AS avg_monthly_rate
FROM ranked r
LEFT JOIN geo_gqp_jbxx j ON UPPER(j.gqpbh) = UPPER(r.gqpbh)
WHERE r.max_recent_change >= :alert_threshold
  AND COALESCE(j.gqpmc, r.gqpmc, r.gqpbh) <> '高切坡'
{county_filter}
GROUP BY r.gqpbh, COALESCE(j.gqpmc, r.gqpmc, r.gqpbh), COALESCE(j.ssqx, r.county, '')
ORDER BY max_recent_change DESC, avg_monthly_rate DESC, latest_monitor_month DESC, point_count DESC
FETCH FIRST {int(limit)} ROWS ONLY
""")
    rows = conn.execute(sql, {"alert_threshold": DISPLACEMENT_ALERT_THRESHOLD_MM}).mappings().all()
    return [
        {
            "gqpbh": _to_str(row["gqpbh"]),
            "gqpmc": _to_str(row["gqpmc"]),
            "ssqx": _to_str(row["ssqx"]),
            "contact_name": _to_str(row["contact_name"]),
            "contact_phone": _to_str(row["contact_phone"]),
            "point_count": int(row["point_count"] or 0),
            "latest_monitor_date": f"2025-{int(row['latest_monitor_month'] or 0):02d}",
            "max_recent_change": round(_to_float(row["max_recent_change"]), 2),
            "avg_monthly_rate": round(_to_float(row["avg_monthly_rate"]), 2),
            "analysis_period": f"{DISPLACEMENT_TEST_START[:7]}至{DISPLACEMENT_TEST_END[:7]}",
            "value_mode": "本期位移年度求和",
        }
        for row in rows
    ]


def _fetch_slope_points(conn, gqpbh: str) -> list[dict]:
    sql = text("""
WITH point_sum AS (
  SELECT
    monitor_point AS jcdbh,
    COUNT(DISTINCT report_month) AS record_count,
    SUM(COALESCE(current_x, 0)) AS x_change,
    SUM(COALESCE(current_y, 0)) AS y_change,
    SUM(COALESCE(current_h, 0)) AS h_change
  FROM ai_professional_monitor_monthly_value
  WHERE gqpbh = :gqpbh
    AND report_year = 2025
    AND report_month BETWEEN 1 AND 12
    AND monitor_point IS NOT NULL
    AND monitor_point <> ''
    AND monitor_point NOT LIKE 'KZ%'
    AND (current_x IS NOT NULL OR current_y IS NOT NULL OR current_h IS NOT NULL)
  GROUP BY monitor_point
),
latest_value AS (
  SELECT
    jcdbh,
    record_count,
    x_change,
    y_change,
    h_change,
    GREATEST(
      ABS(x_change),
      ABS(y_change),
      ABS(h_change)
    ) AS max_recent_change
  FROM point_sum
)
SELECT
  jcdbh,
  record_count,
  x_change,
  y_change,
  h_change,
  max_recent_change,
  max_recent_change / 12 AS avg_monthly_rate
FROM latest_value
WHERE max_recent_change >= :alert_threshold
ORDER BY max_recent_change DESC, jcdbh ASC
FETCH FIRST 8 ROWS ONLY
""")
    rows = conn.execute(sql, {
        "gqpbh": gqpbh,
        "alert_threshold": DISPLACEMENT_ALERT_THRESHOLD_MM,
    }).mappings().all()
    return [
        {
            "jcdbh": _to_str(row["jcdbh"]),
            "record_count": int(row["record_count"] or 0),
            "x_change": round(_to_float(row["x_change"]), 2),
            "y_change": round(_to_float(row["y_change"]), 2),
            "h_change": round(_to_float(row["h_change"]), 2),
            "max_recent_change": round(_to_float(row["max_recent_change"]), 2),
            "avg_monthly_rate": round(_to_float(row["avg_monthly_rate"]), 2),
        }
        for row in rows
    ]


def _attach_qmqf_photos(cards: list[dict]) -> None:
    codes = [_to_str(card.get("gqpbh")) for card in cards if _to_str(card.get("gqpbh"))]
    if not codes:
        return
    escaped_codes = ", ".join("'" + code.replace("'", "''") + "'" for code in sorted(set(codes)))
    sql = f"""
SELECT TOP {max(len(codes) * 80, 200)}
  s.code AS gqpbh,
  m.photoOn,
  m.createdOn,
  m.photoNo1,
  m.photoNo2,
  m.photoNo3,
  m.crackImageUri,
  m.wallCrackingImageUri
FROM tb_hcs_monitoring m
LEFT JOIN tb_hcslope s ON m.hcs_id = s.id
WHERE s.code IN ({escaped_codes})
  AND (
    COALESCE(m.photoNo1, '') <> ''
    OR COALESCE(m.photoNo2, '') <> ''
    OR COALESCE(m.photoNo3, '') <> ''
    OR COALESCE(m.crackImageUri, '') <> ''
    OR COALESCE(m.wallCrackingImageUri, '') <> ''
  )
ORDER BY COALESCE(m.photoOn, m.createdOn) DESC, m.id DESC
""".strip()
    try:
        _, rows, _ = query_sqlserver_for_display(sql, display_limit=max(len(codes) * 80, 200))
    except Exception as exc:
        for card in cards:
            card["photos"] = []
            card["photo_note"] = f"群测群防照片读取失败：{exc}"
        return

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        code = _to_str(row.get("gqpbh"))
        if code:
            grouped.setdefault(code.upper(), []).append(row)

    for card in cards:
        code = _to_str(card.get("gqpbh")).upper()
        selected = _select_qmqf_photos(grouped.get(code, []))
        card["photos"] = selected
        card["photo_note"] = "已从群测群防监测记录匹配现场照片" if selected else "群测群防记录中暂未匹配到现场照片"


def _attach_sqlserver_contacts(cards: list[dict]) -> None:
    missing_cards = [
        card for card in cards
        if _to_str(card.get("gqpbh")) and not (_to_str(card.get("contact_name")) or _to_str(card.get("contact_phone")))
    ]
    if not missing_cards:
        return
    codes = sorted({_to_str(card.get("gqpbh")) for card in missing_cards})
    escaped_codes = ", ".join("'" + code.replace("'", "''") + "'" for code in codes)
    sql = f"""
SELECT
  s.code AS gqpbh,
  COALESCE(
    NULLIF(LTRIM(RTRIM(monitor_ext.name)), ''),
    NULLIF(LTRIM(RTRIM(monitor_user.user_name)), '')
  ) AS contact_name,
  COALESCE(
    NULLIF(LTRIM(RTRIM(monitor_ext.mobile)), ''),
    NULLIF(LTRIM(RTRIM(monitor_ext.telephone)), '')
  ) AS contact_phone
FROM tb_hcslope s
LEFT JOIN tb_system_user monitor_user ON s.monitor_id = monitor_user.user_id
LEFT JOIN tb_system_user_ext monitor_ext ON monitor_user.ext_id = monitor_ext.id
WHERE s.code IN ({escaped_codes})
""".strip()
    try:
        _, rows, _ = query_sqlserver_for_display(sql, display_limit=max(len(codes), 50))
    except Exception:
        return
    contacts = {
        _to_str(row.get("gqpbh")).upper(): row
        for row in rows
        if _to_str(row.get("gqpbh"))
    }
    for card in missing_cards:
        row = contacts.get(_to_str(card.get("gqpbh")).upper())
        if not row:
            continue
        card["contact_name"] = _clean_contact_text(row.get("contact_name"))
        card["contact_phone"] = _clean_contact_text(row.get("contact_phone"))


def _clean_contact_text(value) -> str:
    return clean_card_text(value)


def _select_qmqf_photos(rows: list[dict]) -> list[str]:
    recent: list[str] = []
    history: list[str] = []
    seen: set[str] = set()
    for row in rows:
        photo_time = _to_str(row.get("photoOn") or row.get("createdOn"))
        target = recent if photo_time[:7] >= "2025-06" else history
        for field in ("photoNo1", "photoNo2", "photoNo3", "crackImageUri", "wallCrackingImageUri"):
            value = _to_str(row.get(field)).strip()
            if not value or value.lower() in {"none", "null"} or value in seen:
                continue
            seen.add(value)
            target.append(value)
    selected = recent[:2]
    if len(selected) < 2 and history:
        selected.extend(history[:1])
    return selected[:3]


def _fetch_slope_series(conn, gqpbh: str, point_codes: list[str]) -> dict[str, list[dict]]:
    series: dict[str, list[dict]] = {}
    sql = text("""
SELECT *
FROM (
  SELECT
    report_month,
    monitor_point AS jcdbh,
    current_x,
    current_y,
    current_h,
    GREATEST(
      ABS(COALESCE(current_x, 0)),
      ABS(COALESCE(current_y, 0)),
      ABS(COALESCE(current_h, 0))
    ) AS max_change
  FROM ai_professional_monitor_monthly_value
  WHERE gqpbh = :gqpbh
    AND monitor_point = :jcdbh
    AND report_year = 2025
    AND report_month BETWEEN 1 AND 12
    AND (current_x IS NOT NULL OR current_y IS NOT NULL OR current_h IS NOT NULL)
  ORDER BY report_month DESC
)
WHERE ROWNUM <= 36
""")
    for code in point_codes[:8]:
        rows = conn.execute(sql, {
            "gqpbh": gqpbh,
            "jcdbh": code,
        }).mappings().all()
        ordered = list(reversed(rows))
        series[code] = [
            {
                "date": f"2025-{int(row['report_month'] or 0):02d}",
                "x": round(_to_float(row["current_x"]), 2),
                "y": round(_to_float(row["current_y"]), 2),
                "h": round(_to_float(row["current_h"]), 2),
                "max_change": round(_to_float(row["max_change"]), 2),
            }
            for row in ordered
        ]
    return series


def _linear_slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    return float(np.polyfit(x, y, 1)[0])


def _build_stability(slope: dict, points: list[dict], series: dict[str, list[dict]]) -> dict:
    top_point = points[0]["jcdbh"] if points else ""
    top_rows = series.get(top_point, [])
    all_recent = [point["max_recent_change"] for point in points]
    max_change = max(all_recent) if all_recent else slope["max_recent_change"]
    avg_monthly_rate = max([_to_float(point.get("avg_monthly_rate")) for point in points], default=_to_float(slope.get("avg_monthly_rate")))

    top_values = [row["max_change"] for row in top_rows[-12:]]
    top_slope = _linear_slope(top_values) if len(top_values) >= 2 else 0.0
    current = top_rows[-1]["max_change"] if top_rows else max_change
    next_1 = max(0.0, current + top_slope)
    next_3 = max(0.0, current + top_slope * 3)

    max_slope = 0.0
    for rows in series.values():
        values = [row["max_change"] for row in rows[-12:]]
        max_slope = max(max_slope, abs(_linear_slope(values) if len(values) >= 2 else 0.0))

    if max_change >= 20:
        level = "明显变形"
        advice = "年度位移变化量较大，建议结合月报和现场巡查核查变形趋势。"
    elif max_change >= 10:
        level = "较明显变形"
        advice = "建议保持月度跟踪，关注后续是否持续增大。"
    elif max_change > 0:
        level = "缓慢变形"
        advice = "10mm以下按缓慢变形处理，建议按常规频率跟踪。"
    else:
        level = "无趋势性变形"
        advice = "暂未识别到明确趋势性变形，建议保留常规监测。"

    return {
        "level": level,
        "top_point": top_point,
        "summary": f"{slope['gqpmc']}变化量最大的监测点为{top_point}，2025年度本期位移累计变化量约{max_change:.1f}mm，月度平均变化速率约{avg_monthly_rate:.2f}mm/月。",
        "prediction": f"按2025年度监测序列趋势估算，未来1个月可能达到约{next_1:.1f}mm，未来3个月可能达到约{next_3:.1f}mm。",
        "advice": advice,
        "avg_monthly_rate": round(avg_monthly_rate, 2),
        "analysis_period": f"{DISPLACEMENT_TEST_START[:7]}至{DISPLACEMENT_TEST_END[:7]}",
        "alert_threshold": DISPLACEMENT_ALERT_THRESHOLD_MM,
    }


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)


def _write_point_chart(slope: dict, points: list[dict], series: dict[str, list[dict]], stability: dict) -> dict:
    top_point = stability.get("top_point") or (points[0]["jcdbh"] if points else "")
    point_rows = series.get(top_point, [])
    safe_name = f"{_safe_name(slope['gqpbh'])}_{_safe_name(top_point)}" if top_point else _safe_name(slope["gqpbh"])
    data_path = ASSET_ROOT / f"{safe_name}.json"
    svg_path = ASSET_ROOT / f"{safe_name}.svg"
    data = {"slope": slope, "points": points, "selected_point": top_point, "series": point_rows, "stability": stability}
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    svg = _build_svg_chart(slope, top_point, point_rows, stability)
    svg_path.write_text(svg, encoding="utf-8")
    return {
        "html_url": f"{ASSET_URL_ROOT}/{svg_path.name}",
        "json_url": f"{ASSET_URL_ROOT}/{data_path.name}",
        "svg": svg,
    }


def _build_svg_chart(slope: dict, top_point: str, rows: list[dict], stability: dict) -> str:
    width, height = 1400, 820
    left, right, top, bottom = 112, 42, 214, 100
    plot_w = width - left - right
    plot_h = height - top - bottom
    title = escape(f"{slope['gqpmc']} - {top_point} 位移变化图")
    meta = escape(f"编号 {slope['gqpbh']} · {slope['ssqx']} · X/Y/H 三向位移变化量，单位 mm")

    if not rows:
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#f6f8fb"/><rect x="16" y="16" width="{width - 32}" height="{height - 32}" rx="10" fill="#fff" stroke="#e5e7eb"/>
<text x="32" y="56" font-size="22" font-weight="700" fill="#172033">{title}</text>
<text x="32" y="90" font-size="14" fill="#667085">暂无可绘制的监测数据</text>
</svg>"""

    values = [float(row[key]) for row in rows for key in ("x", "y", "h")]
    min_y, max_y = min(values), max(values)
    if min_y == max_y:
        min_y -= 1
        max_y += 1
    span = max_y - min_y
    min_y -= span * 0.12
    max_y += span * 0.12

    def x_at(index: int) -> float:
        if len(rows) == 1:
            return left + plot_w / 2
        return left + plot_w * index / (len(rows) - 1)

    def y_at(value: float) -> float:
        return top + (max_y - value) / (max_y - min_y) * plot_h

    def points_for(key: str) -> str:
        return " ".join(f"{x_at(index):.1f},{y_at(float(row[key])):.1f}" for index, row in enumerate(rows))

    def circles_for(key: str, color: str) -> str:
        return "".join(
            f'<circle cx="{x_at(index):.1f}" cy="{y_at(float(row[key])):.1f}" r="5.8" '
            f'fill="#fff" stroke="{color}" stroke-width="3"/>'
            for index, row in enumerate(rows)
        )

    grid_parts = []
    for i in range(6):
        y = top + plot_h * i / 5
        value = max_y - (max_y - min_y) * i / 5
        grid_parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#e5edf7"/>')
        grid_parts.append(f'<text x="56" y="{y + 5:.1f}" font-size="16" fill="#475467" text-anchor="end">{value:.1f}</text>')

    threshold_parts = []
    for threshold, label in ((20, "20mm明显变形关注线"), (10, "10mm缓慢变形关注线"), (-10, "-10mm缓慢变形关注线"), (-20, "-20mm明显变形关注线")):
        if min_y <= threshold <= max_y:
            y = y_at(float(threshold))
            threshold_parts.append(
                f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" '
                f'stroke="#f59e0b" stroke-width="1.6" stroke-dasharray="8 7"/>'
            )
            threshold_parts.append(
                f'<text x="{width - right - 8}" y="{y - 7:.1f}" font-size="13" fill="#92400e" text-anchor="end">{escape(label)}</text>'
            )

    label_parts = []
    step = max(1, int(np.ceil(len(rows) / 6)))
    for index, row in enumerate(rows):
        if index % step != 0 and index != len(rows) - 1:
            continue
        x = x_at(index)
        label = escape(str(row["date"])[:7])
        label_parts.append(f'<text x="{x:.1f}" y="{height - 42}" font-size="15" fill="#475467" text-anchor="middle">{label}</text>')

    summary = escape(stability.get("summary", ""))
    prediction = escape(stability.get("prediction", ""))
    advice = escape(stability.get("advice", ""))
    level = escape(stability.get("level", ""))
    current_change = rows[-1]["max_change"] if rows else 0
    prediction_values = re.findall(r"约([\d.]+)mm", prediction)
    if len(prediction_values) >= 2:
        short_prediction = f"1个月约{prediction_values[0]}mm，3个月约{prediction_values[1]}mm"
    else:
        short_prediction = prediction[:30] + ("..." if len(prediction) > 30 else "")
    sequence_note = f"当前序列 {len(rows)} 期" if len(rows) > 1 else "当前仅有 1 期数据，图中以点位展示"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">
<style>
  text {{ font-family: Arial, "Microsoft YaHei", sans-serif; }}
</style>
<rect width="100%" height="100%" fill="#ffffff"/>
<rect x="18" y="18" width="{width - 36}" height="{height - 36}" rx="10" fill="#fff" stroke="#dfe6f1"/>
<text x="36" y="54" font-size="24" font-weight="700" fill="#172033">{title}</text>
<text x="36" y="84" font-size="14" fill="#667085">{meta}</text>
<rect x="36" y="104" width="250" height="52" rx="8" fill="#f8fafc" stroke="#e5eaf3"/>
<text x="52" y="126" font-size="13" fill="#667085">稳定性评价</text>
<text x="52" y="148" font-size="18" font-weight="700" fill="#172033">{level}</text>
<rect x="302" y="104" width="470" height="52" rx="8" fill="#f8fafc" stroke="#e5eaf3"/>
<text x="318" y="126" font-size="13" fill="#667085">当前变化</text>
<text x="318" y="148" font-size="18" font-weight="700" fill="#172033">最大位移变化量约 {current_change:.1f} mm</text>
<rect x="788" y="104" width="576" height="52" rx="8" fill="#f8fafc" stroke="#e5eaf3"/>
<text x="804" y="126" font-size="13" fill="#667085">趋势预测</text>
<text x="804" y="148" font-size="18" font-weight="700" fill="#172033">{short_prediction}</text>
<text x="{width - right}" y="{top - 18}" font-size="15" fill="#64748b" text-anchor="end">{escape(sequence_note)}</text>
{''.join(grid_parts)}
{''.join(threshold_parts)}
<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#94a3b8"/>
<line x1="{left}" y1="{top + plot_h}" x2="{width - right}" y2="{top + plot_h}" stroke="#94a3b8"/>
<polyline points="{points_for('x')}" fill="none" stroke="#2563eb" stroke-width="3.4"/>
<polyline points="{points_for('y')}" fill="none" stroke="#16a34a" stroke-width="3.4"/>
<polyline points="{points_for('h')}" fill="none" stroke="#dc2626" stroke-width="3.4"/>
{circles_for('x', '#2563eb')}
{circles_for('y', '#16a34a')}
{circles_for('h', '#dc2626')}
<text x="{left}" y="{top - 22}" font-size="16" font-weight="700" fill="#475467">位移变化量（mm）</text>
<rect x="{left + 176}" y="{top - 26}" width="26" height="5" rx="2.5" fill="#2563eb"/><text x="{left + 212}" y="{top - 19}" font-size="14" fill="#334155">X向位移变化量</text>
<rect x="{left + 366}" y="{top - 26}" width="26" height="5" rx="2.5" fill="#16a34a"/><text x="{left + 402}" y="{top - 19}" font-size="14" fill="#334155">Y向位移变化量</text>
<rect x="{left + 556}" y="{top - 26}" width="26" height="5" rx="2.5" fill="#dc2626"/><text x="{left + 592}" y="{top - 19}" font-size="14" fill="#334155">H向位移变化量</text>
{''.join(label_parts)}
<text x="{left + plot_w / 2:.1f}" y="{height - 18}" font-size="15" font-weight="700" fill="#475467" text-anchor="middle">监测月份</text>
<text x="{width - right}" y="{top - 44}" font-size="13" fill="#64748b" text-anchor="end">阈值线用于辅助研判，最终以现场复核和连续趋势为准</text>
</svg>"""
