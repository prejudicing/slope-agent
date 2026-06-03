from __future__ import annotations

from app.reports.slope_object_index import enrich_slope_cards
from app.core.sqlserver_db import query_sqlserver_for_display


ABNORMAL_FIELDS = [
    ("isCrack", "裂缝"),
    ("surfaceRockfall", "落石"),
    ("slopeFailure", "坡面异常破坏"),
    ("wallCracking", "道路或挡墙开裂"),
    ("facilities", "监测设施异常"),
    ("disorderlyPush", "坡周乱搭乱堆"),
    ("ditchBlocking", "排水沟堵塞"),
    ("holeBlocking", "排水口堵塞"),
    ("crestIrrigation", "坡顶灌水"),
]


def get_qmqf_abnormal_dashboard(limit: int = 8) -> dict:
    rows = _fetch_rows(limit)
    items = []
    for row in rows:
        abnormal_types = _effective_abnormal_types(row)
        if not abnormal_types:
            continue
        photos = [
            row.get("photoNo1", ""),
            row.get("photoNo2", ""),
            row.get("photoNo3", ""),
            row.get("crackImageUri", ""),
            row.get("wallCrackingImageUri", ""),
        ]
        photos = [photo for photo in photos if str(photo or "").strip()]
        severity = _severity(abnormal_types, row)
        status_text = _status_text(row, abnormal_types)
        evidence = _evidence_text(row, abnormal_types, photos)
        items.append({
            "gqpbh": row.get("gqpbh", ""),
            "gqpmc": row.get("gqpmc", "") or row.get("gqpbh", ""),
            "ssqx": row.get("ssqx", ""),
            "abnormal_types": abnormal_types,
            "abnormal_summary": "、".join(abnormal_types) or "存在异常记录",
            "severity": severity,
            "priority_reason": _priority_reason(severity, abnormal_types, photos),
            "photo_on": _format_time(row.get("photoOn", "") or row.get("createdOn", "")),
            "created_on": _format_time(row.get("createdOn", "")),
            "status_text": status_text,
            "has_crack_marker": False,
            "crack_width": _format_measure(row.get("width")),
            "evidence": evidence,
            "photos": photos[:5],
            "contact_name": row.get("contact_name", ""),
            "contact_phone": row.get("contact_phone", ""),
            "advice": _advice(severity, abnormal_types, photos),
        })

    enrich_slope_cards(items)
    return {
        "status": "success",
        "title": "近期群测群防监测情况",
        "description": "按有效异常细项和现场照片综合展示近期群测群防监测情况。",
        "items": items,
    }


def _fetch_rows(limit: int) -> list[dict]:
    non_crack_fields = [field for field, _ in ABNORMAL_FIELDS if field != "isCrack"]
    fields_condition = " OR ".join(
        ["(m.isCrack = 1 AND NULLIF(LTRIM(RTRIM(CONVERT(varchar(50), m.width))), '') IS NOT NULL)"]
        + [f"m.{field} = 1" for field in non_crack_fields]
    )
    sql = f"""
SELECT TOP {max(int(limit) * 120, 300)}
  s.code AS gqpbh,
  s.name AS gqpmc,
  COALESCE(county.areaname, city.areaname, s.location) AS ssqx,
  m.isCrack,
  m.surfaceRockfall,
  m.slopeFailure,
  m.wallCracking,
  m.facilities,
  m.disorderlyPush,
  m.ditchBlocking,
  m.holeBlocking,
  m.crestIrrigation,
  m.overallSituation,
  m.width,
  m.hcSlopeStatus,
  m.statusReason,
  m.photoOn,
  m.photoNo1,
  m.photoNo2,
  m.photoNo3,
  m.crackImageUri,
  m.wallCrackingImageUri,
  m.createdOn,
  COALESCE(
    NULLIF(LTRIM(RTRIM(monitor_ext.name)), ''),
    NULLIF(LTRIM(RTRIM(create_ext.name)), ''),
    NULLIF(LTRIM(RTRIM(monitor_user.user_name)), ''),
    NULLIF(LTRIM(RTRIM(create_user.user_name)), '')
  ) AS contact_name,
  COALESCE(
    NULLIF(LTRIM(RTRIM(monitor_ext.mobile)), ''),
    NULLIF(LTRIM(RTRIM(create_ext.mobile)), ''),
    NULLIF(LTRIM(RTRIM(monitor_ext.telephone)), ''),
    NULLIF(LTRIM(RTRIM(create_ext.telephone)), '')
  ) AS contact_phone
FROM tb_hcs_monitoring m
LEFT JOIN tb_hcslope s ON m.hcs_id = s.id
LEFT JOIN tb_area_china county ON s.county_id = county.areano
LEFT JOIN tb_area_china city ON s.city_id = city.areano
LEFT JOIN tb_system_user monitor_user ON s.monitor_id = monitor_user.user_id
LEFT JOIN tb_system_user_ext monitor_ext ON monitor_user.ext_id = monitor_ext.id
LEFT JOIN tb_system_user create_user ON m.create_user_id = create_user.user_id
LEFT JOIN tb_system_user_ext create_ext ON create_user.ext_id = create_ext.id
WHERE {fields_condition}
ORDER BY m.createdOn DESC, m.id DESC
""".strip()
    _, rows, _ = query_sqlserver_for_display(sql, display_limit=max(int(limit) * 120, 300))
    seen = set()
    county_counts = {}
    unique_rows = []
    deferred_rows = []
    for row in rows:
        key = row.get("gqpbh") or row.get("gqpmc")
        if not key or key in seen:
            continue
        county = row.get("ssqx") or "未标注区县"
        if county_counts.get(county, 0) >= 2:
            deferred_rows.append(row)
            continue
        seen.add(key)
        county_counts[county] = county_counts.get(county, 0) + 1
        unique_rows.append(row)
        if len(unique_rows) >= limit:
            break
    if len(unique_rows) < limit:
        for row in deferred_rows:
            key = row.get("gqpbh") or row.get("gqpmc")
            if not key or key in seen:
                continue
            seen.add(key)
            unique_rows.append(row)
            if len(unique_rows) >= limit:
                break
    return unique_rows


def _effective_abnormal_types(row: dict) -> list[str]:
    abnormal_types = []
    for field, label in ABNORMAL_FIELDS:
        if not _is_truthy_flag(row.get(field)):
            continue
        if field == "isCrack" and not _format_measure(row.get("width")):
            continue
        abnormal_types.append(label)
    return abnormal_types


def _is_truthy_flag(value) -> bool:
    return str(value or "").strip() in {"1", "1.0", "true", "True"}


def _evidence_text(row: dict, abnormal_types: list[str], photos: list[str]) -> str:
    evidence = []
    if "裂缝" in abnormal_types:
        evidence.append(f"系统细项 isCrack=1，裂缝宽度 {_format_measure(row.get('width'))} mm")
        if str(row.get("crackImageUri") or "").strip():
            evidence.append("已匹配裂缝照片")
    if "道路或挡墙开裂" in abnormal_types and str(row.get("wallCrackingImageUri") or "").strip():
        evidence.append("已匹配道路或挡墙开裂照片")
    other_types = [item for item in abnormal_types if item not in {"裂缝", "道路或挡墙开裂"}]
    if other_types:
        evidence.append("系统细项：" + "、".join(other_types))
    if photos:
        evidence.append(f"现场照片 {len(photos)} 张，用于人工复核")
    return "；".join(evidence) or "按系统异常细项判定"


def _format_time(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.replace("T", " ")[:16]


def _format_measure(value) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "null"}:
        return ""
    try:
        return f"{float(text):.1f}"
    except ValueError:
        return text


def _status_text(row: dict, abnormal_types: list[str]) -> str:
    for key in ("statusReason", "hcSlopeStatus", "overallSituation"):
        value = str(row.get(key, "") or "").strip()
        if not value or value.lower() in {"none", "null"}:
            continue
        if value.lower() == "true":
            return "已发现异常"
        if value.lower() == "false":
            continue
        if value in {"1", "1.0"}:
            return "已发现异常"
        if value in {"0", "0.0"}:
            continue
        return value
    return "异常项：" + ("、".join(abnormal_types) or "存在异常记录")


def _severity(abnormal_types: list[str], row: dict) -> str:
    major = {"坡面异常破坏", "道路或挡墙开裂", "落石"}
    if any(item in major for item in abnormal_types):
        return "重点复核"
    if "裂缝" in abnormal_types:
        return "现场复核"
    if len(abnormal_types) >= 2:
        return "持续跟踪"
    return "一般关注"


def _priority_reason(severity: str, abnormal_types: list[str], photos: list[str]) -> str:
    types = set(abnormal_types)
    if severity == "重点复核":
        matched = [item for item in ("坡面异常破坏", "落石", "道路或挡墙开裂") if item in types]
        return "识别到" + "、".join(matched) + "，属于需要优先核实的明显破坏或风险迹象。"
    if severity == "现场复核":
        return "当前主要为裂缝类记录，需要现场核实宽度、长度和是否持续扩展，暂不直接判定为最高等级。"
    if severity == "持续跟踪":
        return "存在多个一般异常项，建议连续跟踪其变化，但尚未达到明显破坏判定条件。"
    if photos:
        return "存在单项异常记录和现场照片，建议纳入常规巡查台账。"
    return "存在单项异常记录，建议常规巡查并补充现场照片。"


def _advice(severity: str, abnormal_types: list[str], photos: list[str]) -> str:
    if severity == "重点复核":
        base = "建议安排现场复核，重点核查落石、坡面破坏、挡墙或道路开裂等异常部位扩展情况，并结合照片留痕。"
    elif severity == "现场复核":
        base = "建议对裂缝部位开展现场复核，核实裂缝宽度、延伸长度和近期变化，不宜直接判定为最高等级。"
    elif severity == "持续跟踪":
        base = "建议保持近期跟踪，下一轮巡查重点比对异常项是否扩大。"
    else:
        base = "建议纳入常规巡查台账，持续观察异常项变化。"
    if not photos:
        base += " 当前记录未匹配到有效现场照片，建议补充拍照。"
    return base
