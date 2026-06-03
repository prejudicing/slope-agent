from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from app.core.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER
from app.reports.slope_object_index import build_slope_object_index, enrich_slope_cards, normalize_code


SLOPE_CODE_RE = re.compile(r"(?:E?XS|E?ZG|ZG|BD|YL|FJ)\s*[0-9A-Z]{3,}(?:\s*0A\d{3})?\*?", re.IGNORECASE)
SLOPE_NAME_RE = re.compile(r"([\u4e00-\u9fffA-Za-z0-9（）()·\-]{2,40}\u9ad8\u5207\u5761)")


def _engine():
    password = quote_plus(DM_PASSWORD)
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def _json_list(value) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(str(value))
        if isinstance(data, list):
            return [str(item) for item in data if item]
    except Exception:
        pass
    return []


def _compact_code(value) -> str:
    return re.sub(r"[\s*]+", "", str(value or "")).upper()


def _first_report_slope_code(text_value: str) -> tuple[str, int] | tuple[str, None]:
    for match in SLOPE_CODE_RE.finditer(text_value[:320]):
        code = _compact_code(match.group(0))
        if code.startswith("JC"):
            continue
        return code, match.start()
    return "", None


def _extract_name_after_code(text_value: str, code: str) -> str:
    if not code:
        return ""
    compact_text = re.sub(r"\s+", "", text_value)
    compact_code = _compact_code(code)
    start = compact_text.find(compact_code)
    if start < 0:
        return ""
    after = compact_text[start + len(compact_code): start + len(compact_code) + 80]
    match = SLOPE_NAME_RE.search(after)
    return match.group(1) if match else ""


def _clean_report_text(text_value: str, code: str = "", name: str = "") -> str:
    clean = re.sub(r"\s+", "", str(text_value or ""))
    clean = re.sub(r"^\d+(?=\u5e8f\u53f7)", "", clean)
    clean = re.sub(r"^\d+(?:\.\d+)+", "", clean)
    clean = re.sub(r"^\u5e8f\u53f7\u7f16\u53f7\u9ad8\u5207\u5761\u540d\u79f0\u5b8f\u89c2\u5de1\u89c6\u5de1\u89c6\u56fe\u7247\d*", "", clean)
    if "\u7ed3\u8bba" in clean and clean.find("\u7ed3\u8bba") < 80:
        clean = clean.split("\u7ed3\u8bba", 1)[1]
    if code:
        compact_code = _compact_code(code)
        pos = clean.find(compact_code)
        if 0 <= pos <= 80:
            clean = clean[pos + len(compact_code):]
    if name and clean.startswith(name):
        clean = clean[len(name):]
    clean = re.sub(r"^[-—:：；;、.．）)]+", "", clean)
    return clean[:600]


def _repair_report_items(items: list[dict]) -> list[dict]:
    candidates: set[str] = set()
    for item in items:
        code, pos = _first_report_slope_code(item.get("stability_text") or "")
        current = _compact_code(item.get("gqpbh"))
        if code and code != current and (pos is not None and pos <= 80):
            candidates.add(code)
    index = build_slope_object_index(sorted(candidates)) if candidates else {}
    for item in items:
        text_value = item.get("stability_text") or ""
        current = _compact_code(item.get("gqpbh"))
        name = str(item.get("gqpmc") or "")
        name_code_prefix = re.match(r"^(0A\d{3})(.+)$", name)
        if current and name_code_prefix:
            current = f"{current}{name_code_prefix.group(1)}"
            item["gqpbh"] = current
            item["gqpmc"] = name_code_prefix.group(2)
        embedded_code, pos = _first_report_slope_code(text_value)
        embedded_name = _extract_name_after_code(text_value, embedded_code)
        if embedded_code and embedded_code != current and (pos is not None and pos <= 80):
            item["gqpbh"] = embedded_code
            if index.get(embedded_code, {}).get("gqpmc"):
                item["gqpmc"] = index[embedded_code]["gqpmc"]
            elif embedded_name:
                item["gqpmc"] = embedded_name
            item["stability_text"] = _clean_report_text(text_value, embedded_code, item.get("gqpmc") or "")
        else:
            item["gqpbh"] = normalize_code(item.get("gqpbh")) or item.get("gqpbh", "")
            item["stability_text"] = _clean_report_text(text_value)
    return items


def get_recent_report_stability_assets(
    *,
    limit: int = 12,
    county: str = "",
    gqpbh: str = "",
    only_with_photos: bool = False,
) -> dict:
    """读取近期月报稳定性评价和关联照片资产。"""
    filters = ["report_year = 2025", "report_month BETWEEN 9 AND 12"]
    params = {"limit": max(1, int(limit))}
    if county:
        filters.append("county = :county")
        params["county"] = county
    if gqpbh:
        filters.append("UPPER(gqpbh) = :gqpbh")
        params["gqpbh"] = gqpbh.upper()
    if only_with_photos:
        filters.append("related_photo_count > 0")
    filters.append("COALESCE(confidence, '') <> '重复文本已排除'")
    where_clause = " AND ".join(filters)
    sql = text(f"""
SELECT *
FROM (
  SELECT
    county,
    report_year,
    report_month,
    report_type,
    file_name,
    page_no,
    gqpbh,
    gqpmc,
    stability_level,
    stability_text,
    abnormal_keywords,
    related_photo_count,
    photo_urls,
    thumbnail_urls,
    confidence,
    ROW_NUMBER() OVER (
      PARTITION BY COALESCE(gqpbh, ''), stability_level
      ORDER BY report_year DESC, report_month DESC, related_photo_count DESC, page_no ASC
    ) AS rn,
    ROW_NUMBER() OVER (
      PARTITION BY county, report_year, report_month, page_no, SUBSTR(stability_text, 1, 240)
      ORDER BY related_photo_count DESC, gqpbh ASC
    ) AS text_rn
  FROM ai_report_stability_asset
  WHERE {where_clause}
)
WHERE rn = 1 AND text_rn = 1
ORDER BY
  CASE stability_level
    WHEN '需现场复核' THEN 0
    WHEN '局部异常需跟踪' THEN 1
    WHEN '总体较稳定' THEN 2
    ELSE 3
  END,
  related_photo_count DESC,
  report_month DESC
FETCH FIRST :limit ROWS ONLY
""")
    engine = _engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
    finally:
        engine.dispose()
    items = []
    for row in rows:
        items.append({
            "county": str(row.get("county") or ""),
            "report_year": int(row.get("report_year") or 0),
            "report_month": int(row.get("report_month") or 0),
            "report_type": str(row.get("report_type") or ""),
            "file_name": str(row.get("file_name") or ""),
            "page_no": int(row.get("page_no") or 0) or None,
            "gqpbh": str(row.get("gqpbh") or ""),
            "gqpmc": str(row.get("gqpmc") or row.get("gqpbh") or ""),
            "stability_level": str(row.get("stability_level") or ""),
            "stability_text": str(row.get("stability_text") or ""),
            "abnormal_keywords": str(row.get("abnormal_keywords") or ""),
            "related_photo_count": int(row.get("related_photo_count") or 0),
            "photo_urls": _json_list(row.get("photo_urls")),
            "thumbnail_urls": _json_list(row.get("thumbnail_urls")),
            "confidence": str(row.get("confidence") or ""),
        })
    _repair_report_items(items)
    enrich_slope_cards(items)
    return {
        "status": "success",
        "title": "近期月报稳定性评价与现场照片",
        "description": "按2025年9-12月月报提取稳定性评价、异常描述和邻近现场照片。",
        "items": items,
    }
