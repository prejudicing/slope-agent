from __future__ import annotations

import re
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from app.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER
from app.sqlserver_db import query_sqlserver_for_display


GENERIC_NAMES = {"", "高切坡", "未命名高切坡", "高切坡名称待核实", "None", "null"}
MOJIBAKE_RE = re.compile(r"[\u0400-\u04ff\ufffd]")


def clean_card_text(value) -> str:
    text_value = "" if value is None else str(value).strip()
    if not text_value or text_value in GENERIC_NAMES or text_value.lower() in {"none", "null", "undefined"}:
        return ""
    if MOJIBAKE_RE.search(text_value):
        return ""
    return text_value


def normalize_code(value) -> str:
    return clean_card_text(value).upper()


def enrich_slope_cards(cards: list[dict], *, code_key: str = "gqpbh") -> list[dict]:
    """统一补齐卡片上的高切坡名称、区县、联系人和联系电话。"""
    codes = sorted({normalize_code(card.get(code_key)) for card in cards if normalize_code(card.get(code_key))})
    if not codes:
        for card in cards:
            _normalize_existing_card(card)
        return cards

    index = build_slope_object_index(codes)
    for card in cards:
        _normalize_existing_card(card)
        code = normalize_code(card.get(code_key))
        info = index.get(code, {})
        _apply_index_info(card, info)
    return cards


def build_slope_object_index(codes: list[str]) -> dict[str, dict]:
    normalized_codes = sorted({normalize_code(code) for code in codes if normalize_code(code)})
    if not normalized_codes:
        return {}
    merged: dict[str, dict] = {}
    for source_rows in (_fetch_dm_objects(normalized_codes), _fetch_sqlserver_objects(normalized_codes)):
        for row in source_rows:
            code = normalize_code(row.get("gqpbh"))
            if not code:
                continue
            current = merged.setdefault(code, {"gqpbh": code})
            _merge_value(current, "gqpmc", row.get("gqpmc"))
            _merge_value(current, "ssqx", row.get("ssqx"))
            _merge_value(current, "contact_name", row.get("contact_name"))
            _merge_value(current, "contact_phone", row.get("contact_phone"))
            _merge_value(current, "management_unit", row.get("management_unit"))
            _merge_value(current, "professional_unit", row.get("professional_unit"))
    return merged


def _normalize_existing_card(card: dict) -> None:
    for key in ("gqpbh", "gqpmc", "ssqx", "county", "contact_name", "contact_phone", "management_unit", "professional_unit"):
        if key in card:
            card[key] = clean_card_text(card.get(key))


def _apply_index_info(card: dict, info: dict) -> None:
    if not info:
        card.setdefault("data_quality", "对象信息待校核")
        return
    if clean_card_text(info.get("gqpmc")) and not clean_card_text(card.get("gqpmc")):
        card["gqpmc"] = clean_card_text(info.get("gqpmc"))
    if clean_card_text(info.get("ssqx")) and not clean_card_text(card.get("ssqx")):
        card["ssqx"] = clean_card_text(info.get("ssqx"))
    if clean_card_text(info.get("ssqx")) and "county" in card and not clean_card_text(card.get("county")):
        card["county"] = clean_card_text(info.get("ssqx"))
    if clean_card_text(info.get("contact_name")) and not clean_card_text(card.get("contact_name")):
        card["contact_name"] = clean_card_text(info.get("contact_name"))
    if clean_card_text(info.get("contact_phone")) and not clean_card_text(card.get("contact_phone")):
        card["contact_phone"] = clean_card_text(info.get("contact_phone"))
    if clean_card_text(info.get("management_unit")):
        card["management_unit"] = clean_card_text(info.get("management_unit"))
    if clean_card_text(info.get("professional_unit")):
        card["professional_unit"] = clean_card_text(info.get("professional_unit"))
    missing = [
        label
        for key, label in (("gqpmc", "名称"), ("ssqx", "区县"), ("contact_name", "联系人"), ("contact_phone", "电话"))
        if not clean_card_text(card.get(key))
    ]
    if "county" in card and "ssqx" not in card:
        missing = [
            label
            for key, label in (("gqpmc", "名称"), ("county", "区县"), ("contact_name", "联系人"), ("contact_phone", "电话"))
            if not clean_card_text(card.get(key))
        ]
    card["data_quality"] = "、".join(missing) + "待补齐" if missing else "对象信息完整"


def _merge_value(target: dict, key: str, value) -> None:
    text_value = clean_card_text(value)
    if text_value and not clean_card_text(target.get(key)):
        target[key] = text_value


def _fetch_dm_objects(codes: list[str]) -> list[dict]:
    values = ", ".join("'" + code.replace("'", "''") + "'" for code in codes)
    sql = text(f"""
SELECT
  UPPER(gqpbh) AS gqpbh,
  gqpmc,
  ssqx,
  COALESCE(NULLIF(zrdwfzr, ''), NULLIF(PTU_CONTACT, ''), NULLIF(DISTRICT_MANAGEMENT_STAFF, '')) AS contact_name,
  COALESCE(NULLIF(zrdwfzrdh, ''), NULLIF(PTU_PHONE, '')) AS contact_phone,
  zrdw AS management_unit,
  PROFESSIONAL_TECHNICAL_UNIT AS professional_unit
FROM geo_gqp_jbxx
WHERE UPPER(gqpbh) IN ({values})
""")
    engine = create_engine(f"dm+dmPython://{DM_USER}:{quote_plus(DM_PASSWORD)}@{DM_HOST}:{DM_PORT}/")
    try:
        with engine.connect() as conn:
            return [dict(row) for row in conn.execute(sql).mappings().all()]
    except Exception:
        return []
    finally:
        engine.dispose()


def _fetch_sqlserver_objects(codes: list[str]) -> list[dict]:
    values = ", ".join("'" + code.replace("'", "''") + "'" for code in codes)
    sql = f"""
SELECT
  UPPER(s.code) AS gqpbh,
  s.name AS gqpmc,
  COALESCE(county.areaname, city.areaname, s.location) AS ssqx,
  COALESCE(
    NULLIF(LTRIM(RTRIM(monitor_ext.name)), ''),
    NULLIF(LTRIM(RTRIM(monitor_user.user_name)), '')
  ) AS contact_name,
  COALESCE(
    NULLIF(LTRIM(RTRIM(monitor_ext.mobile)), ''),
    NULLIF(LTRIM(RTRIM(monitor_ext.telephone)), '')
  ) AS contact_phone,
  '' AS management_unit,
  '' AS professional_unit
FROM tb_hcslope s
LEFT JOIN tb_area_china county ON s.county_id = county.areano
LEFT JOIN tb_area_china city ON s.city_id = city.areano
LEFT JOIN tb_system_user monitor_user ON s.monitor_id = monitor_user.user_id
LEFT JOIN tb_system_user_ext monitor_ext ON monitor_user.ext_id = monitor_ext.id
WHERE UPPER(s.code) IN ({values})
""".strip()
    try:
        _, rows, _ = query_sqlserver_for_display(sql, display_limit=max(len(codes), 50))
        return rows
    except Exception:
        return []
