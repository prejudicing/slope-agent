from __future__ import annotations

import json
import re
from decimal import Decimal
from html import escape
from pathlib import Path
from urllib.parse import quote, quote_plus

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import create_engine, text

from app.core.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER
from app.core.sqlserver_db import query_sqlserver_for_display


CODE_RE = re.compile(r"(?<![A-Z0-9])[A-Z]{1,4}\d{3,5}[A-Z]?\*?(?![A-Z0-9])", re.IGNORECASE)
CHART_ROOT = Path(__file__).resolve().parents[2] / "generated" / "single_slope_charts"
CHART_URL_ROOT = "/report-assets/single_slope_charts"


def extract_slope_code(question: str) -> str:
    match = CODE_RE.search((question or "").upper())
    return match.group(0).upper() if match else ""


def get_single_slope_field_status(question: str) -> tuple[list[str], list[dict], int]:
    code = extract_slope_code(question)
    if not code:
        return [], [], 0

    basic = _fetch_basic(code)
    professional = _fetch_professional(code)
    report = _fetch_report_context(code)
    qmqf = _fetch_qmqf_records(code)

    rows: list[dict] = []
    if basic:
        rows.append({
            "项目": "基础信息",
            "简要内容": _basic_text(basic, compact=True),
            "时间": "",
            "现场照片": "",
            "gqpbh": code,
        })
    if report:
        rows.append({
            "项目": "历史评价",
            "简要内容": report.get("brief", "") or report.get("summary", ""),
            "时间": report.get("time", ""),
            "现场照片": _photo_summary(report.get("photo_count", "")),
            "gqpbh": code,
        })
    if qmqf:
        rows.append({
            "项目": "群测群防",
            "简要内容": _qmqf_text(qmqf, compact=True),
            "时间": qmqf[0].get("记录时间", ""),
            "现场照片": _photo_summary(sum(_safe_int(item.get("照片数")) for item in qmqf)),
            "gqpbh": code,
            "photoNo1": qmqf[0].get("照片1", ""),
            "photoNo2": qmqf[0].get("照片2", ""),
            "photoNo3": qmqf[0].get("照片3", ""),
            "wallCrackingImageUri": qmqf[0].get("挡墙照片", ""),
            "crackImageUri": qmqf[0].get("裂缝照片", ""),
        })
    if professional:
        rows.append({
            "项目": "专业监测",
            "简要内容": _professional_text(professional, compact=True),
            "时间": professional.get("latest_time", ""),
            "现场照片": "",
            "gqpbh": code,
        })

    if not rows:
        rows.append({
            "项目": "查询结果",
            "简要内容": f"暂未检索到编号 {code} 对应的基础资料、群测群防或专业监测记录。",
            "时间": "",
            "现场照片": "",
            "gqpbh": code,
        })

    return ["项目", "简要内容", "时间", "现场照片"], rows, len(rows)


def _dm_engine():
    password = quote_plus(DM_PASSWORD)
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def _fetch_basic(code: str) -> dict:
    engine = _dm_engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
SELECT
  GQPBH AS code,
  GQPMC AS name,
  SSQX AS county,
  SSJD AS township,
  JSDD AS address,
  SSPC_M AS slope_length,
  SSPG_M AS slope_height,
  SSPJ AS slope_angle,
  SSPMMJ_PM AS slope_area,
  AQDJ AS safety_level,
  JZLX AS type_level,
  ZYJC AS professional_monitoring,
  SFQCQF AS qmqf_monitoring,
  JCJL AS monitor_conclusion,
  SJBGYY AS design_note,
  XMFRDW AS owner_unit,
  HTGQ AS construction_period,
  KCDW AS survey_unit,
  SJDW AS design_unit,
  SGDW AS construction_unit,
  JLDW AS supervision_unit,
  KGRQ AS start_date,
  WGRQ AS finish_date,
  JGRQ AS completion_date,
  JGYSRQ AS acceptance_date,
  GJYSRQ AS final_acceptance_date,
  TBRQ AS fill_date,
  JGRQ AS build_date,
  X AS longitude,
  Y AS latitude
FROM geo_gqp_jbxx
WHERE UPPER(GQPBH) = :code
FETCH FIRST 1 ROWS ONLY
"""), {"code": code}).mappings().first()
        return dict(row or {})
    finally:
        engine.dispose()


def _fetch_professional(code: str) -> dict:
    engine = _dm_engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
SELECT
  monitor_point,
  COUNT(DISTINCT report_month) AS month_count,
  MAX(report_year) AS report_year,
  MAX(report_month) AS latest_month,
  SUM(COALESCE(current_x, 0)) AS x_change,
  SUM(COALESCE(current_y, 0)) AS y_change,
  SUM(COALESCE(current_h, 0)) AS h_change,
  MAX(ABS(COALESCE(current_x, 0))) AS max_monthly_x,
  MAX(ABS(COALESCE(current_y, 0))) AS max_monthly_y,
  MAX(ABS(COALESCE(current_h, 0))) AS max_monthly_h
FROM ai_professional_monitor_monthly_value
WHERE report_year = 2025
  AND UPPER(gqpbh) = :code
  AND monitor_point IS NOT NULL
  AND monitor_point <> ''
GROUP BY monitor_point
ORDER BY GREATEST(
  ABS(SUM(COALESCE(current_x, 0))),
  ABS(SUM(COALESCE(current_y, 0))),
  ABS(SUM(COALESCE(current_h, 0)))
) DESC
FETCH FIRST 6 ROWS ONLY
"""), {"code": code}).mappings().all()
    finally:
        engine.dispose()

    items = [dict(row) for row in rows]
    if not items:
        return {}
    top = items[0]
    latest_year = _safe_int(top.get("report_year")) or 2025
    latest_month = max(_safe_int(item.get("latest_month")) for item in items)
    return {
        "items": items,
        "top_point": top.get("monitor_point", ""),
        "top_change": _max_axis_change(top),
        "latest_time": f"{latest_year}-{latest_month:02d}" if latest_month else str(latest_year),
    }


def _fetch_report_context(code: str) -> dict:
    engine = _dm_engine()
    try:
        with engine.connect() as conn:
            asset = conn.execute(text("""
SELECT
  report_year,
  report_month,
  stability_level,
  stability_text,
  abnormal_keywords,
  related_photo_count
FROM ai_report_stability_asset
WHERE UPPER(gqpbh) = :code
ORDER BY report_year DESC NULLS LAST, report_month DESC NULLS LAST, page_no ASC
FETCH FIRST 1 ROWS ONLY
"""), {"code": code}).mappings().first()
            chunk = conn.execute(text("""
SELECT content
FROM ai_monthly_report_chunk
WHERE content LIKE '%' || :code || '%'
ORDER BY
  CASE
    WHEN content LIKE '%调查情况%' AND content LIKE '%整改建议%' THEN 0
    WHEN content LIKE '%裂缝%' OR content LIKE '%挡墙%' OR content LIKE '%位移%' THEN 1
    ELSE 2
  END,
  CASE WHEN report_type LIKE '%安全评估%' THEN 0 ELSE 1 END,
  report_year DESC NULLS LAST,
  report_month DESC NULLS LAST,
  chunk_index ASC
FETCH FIRST 1 ROWS ONLY
"""), {"code": code}).mappings().first()
            assessment_rows = conn.execute(text("""
SELECT content
FROM ai_monthly_report_chunk
WHERE content LIKE '%' || :code || '%'
  AND (
    content LIKE '%不稳定%'
    OR content LIKE '%局部不稳定%'
    OR content LIKE '%基本稳定%'
    OR content LIKE '%稳定%'
  )
ORDER BY
  CASE WHEN report_type LIKE '%安全评估%' THEN 0 ELSE 1 END,
  chunk_index ASC
FETCH FIRST 6 ROWS ONLY
"""), {"code": code}).mappings().all()
    finally:
        engine.dispose()

    report_text = ""
    if chunk:
        report_text = _extract_code_section(str(chunk.get("content") or ""), code)
    if not report_text and asset:
        report_text = str(asset.get("stability_text") or "")
    if not report_text and not asset:
        return {}

    level = _extract_assessment_level([str(row.get("content") or "") for row in assessment_rows], code)
    if not level and asset:
        level = str(asset.get("stability_level") or "")
    keywords = str(asset.get("abnormal_keywords") or "") if asset else ""
    photo_count = _safe_int(asset.get("related_photo_count")) if asset else 0
    time_text = ""
    if asset and asset.get("report_year") and asset.get("report_month"):
        time_text = f"{_safe_int(asset.get('report_year'))}-{_safe_int(asset.get('report_month')):02d}"
    summary_parts = []
    if level:
        summary_parts.append(f"稳定性评价为{level}")
    if keywords and keywords not in {"异常", "现场异常"}:
        summary_parts.append(f"涉及{keywords}")
    cleaned = _compact_report_text(report_text)
    if cleaned:
        summary_parts.append(cleaned)
    return {
        "summary": "；".join(summary_parts),
        "brief": _brief_report_text("；".join(summary_parts)),
        "time": time_text,
        "photo_count": photo_count or "",
    }


def _fetch_qmqf_records(code: str) -> list[dict]:
    sql = """
SELECT TOP 5
  s.code AS 高切坡编号,
  s.name AS 高切坡名称,
  COALESCE(county.areaname, city.areaname, s.location) AS 所属区县,
  m.createdOn AS 记录时间,
  m.statusReason AS 状态说明,
  m.isCrack,
  m.surfaceRockfall,
  m.slopeFailure,
  m.wallCracking,
  m.facilities,
  m.disorderlyPush,
  m.ditchBlocking,
  m.holeBlocking,
  m.crestIrrigation,
  m.width,
  m.photoNo1 AS 照片1,
  m.photoNo2 AS 照片2,
  m.photoNo3 AS 照片3,
  m.crackImageUri AS 裂缝照片,
  m.wallCrackingImageUri AS 挡墙照片
FROM tb_hcs_monitoring m
LEFT JOIN tb_hcslope s ON m.hcs_id = s.id
LEFT JOIN tb_area_china county ON s.county_id = county.areano
LEFT JOIN tb_area_china city ON s.city_id = city.areano
WHERE UPPER(s.code) = '{code}'
ORDER BY m.createdOn DESC, m.id DESC
""".strip().format(code=code.replace("'", "''"))
    try:
        _, raw_rows, _ = query_sqlserver_for_display(sql, display_limit=5)
    except Exception:
        return []
    rows = []
    for row in raw_rows:
        photos = [
            row.get("照片1"),
            row.get("照片2"),
            row.get("照片3"),
            row.get("裂缝照片"),
            row.get("挡墙照片"),
        ]
        rows.append({
            **row,
            "异常类型": "、".join(_abnormal_types(row)),
            "照片数": len([item for item in photos if str(item or "").strip()]),
            "记录时间": str(row.get("记录时间") or "").replace("T", " ")[:16],
        })
    return rows


def _basic_text(row: dict, *, compact: bool = False) -> str:
    name = row.get("name") or row.get("code")
    county = row.get("county") or ""
    township = row.get("township") or ""
    address = row.get("address") or ""
    size = []
    if row.get("slope_length"):
        size.append(f"坡长约{_fmt(row.get('slope_length'))}m")
    if row.get("slope_height"):
        size.append(f"坡高约{_fmt(row.get('slope_height'))}m")
    if row.get("slope_angle"):
        size.append(f"坡角约{_fmt(row.get('slope_angle'))}°")
    build_time = _build_time_text(row)
    level = row.get("safety_level") or ""
    monitors = []
    if row.get("qmqf_monitoring"):
        monitors.append(f"群测群防：{row.get('qmqf_monitoring')}")
    if row.get("professional_monitoring"):
        monitors.append(f"专业监测：{row.get('professional_monitoring')}")
    region = township or county
    if county and township and not str(township).startswith(str(county)):
        region = f"{county}{township}"
    text_value = (
        f"{region}{name}位于{address or township or county}，"
        f"{'，'.join(size)}。"
        f"{f'安全等级为{level}，' if level else ''}"
        f"{'；'.join(monitors)}。"
    ).strip("。") + "。"
    if compact:
        unit_parts = []
        if row.get("owner_unit"):
            unit_parts.append(f"建设单位为{row.get('owner_unit')}")
        survey_design = row.get("design_unit") or row.get("survey_unit")
        if survey_design:
            unit_parts.append(f"勘察设计单位为{survey_design}")
        if row.get("construction_unit"):
            unit_parts.append(f"施工单位为{row.get('construction_unit')}")
        if row.get("supervision_unit"):
            unit_parts.append(f"监理单位为{row.get('supervision_unit')}")
        level_part = f"安全等级为{level}" if level else ""
        monitor_part = "，".join(monitors)
        return (
            f"{name}位于{address or township or county}，属三峡库区高切坡监测对象。"
            f"基础资料显示，该坡{build_time}，{'，'.join(size) or '规模信息待补充'}"
            f"{f'，{level_part}' if level_part else ''}。"
            f"{f'{monitor_part}。' if monitor_part else ''}"
            f"{'；'.join(unit_parts)}。"
        )
    return text_value


def _qmqf_text(rows: list[dict], *, compact: bool = False) -> str:
    latest = rows[0]
    types = "、".join(dict.fromkeys(t for row in rows for t in str(row.get("异常类型") or "").split("、") if t))
    status = str(latest.get("状态说明") or "").strip()
    photo_count = sum(_safe_int(row.get("照片数")) for row in rows)
    if compact:
        return f"近期记录以{types or '现场异常'}为主。"
    return (
        f"近期群测群防记录主要反映{types or '现场异常'}。"
        f"{f'最新记录说明为“{status}”。' if status else ''}"
        f"已匹配现场照片{photo_count}张，可用于现场复核对照。"
    )


def _professional_text(payload: dict, *, compact: bool = False) -> str:
    items = payload.get("items") or []
    top_point = payload.get("top_point") or ""
    top_change = payload.get("top_change") or {}
    axis = top_change.get("axis", "")
    value = top_change.get("value", 0)
    top = items[0] if items else {}
    top_detail = f"X{_fmt(top.get('x_change'))}、Y{_fmt(top.get('y_change'))}、H{_fmt(top.get('h_change'))}mm" if top else ""
    if compact:
        return f"{top_point}变化相对较大，{axis}年度累计变化约{_fmt(value)}mm。"
    return (
        f"专业监测点{top_point}变化相对较大，{axis}年度累计变化约{_fmt(value)}mm。"
        f"该点2025年累计变化为：{top_detail}。"
    )


def _abnormal_types(row: dict) -> list[str]:
    mapping = [
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
    result = []
    for key, label in mapping:
        if str(row.get(key) or "").strip() in {"1", "1.0", "true", "True"}:
            if key == "isCrack" and not str(row.get("width") or "").strip():
                continue
            result.append(label)
    return result


def _max_axis_change(row: dict) -> dict:
    values = [
        ("X向", _to_float(row.get("x_change"))),
        ("Y向", _to_float(row.get("y_change"))),
        ("H向", _to_float(row.get("h_change"))),
    ]
    axis, value = max(values, key=lambda item: abs(item[1]))
    return {"axis": axis, "value": value}


def _extract_code_section(content: str, code: str) -> str:
    normalized = content or ""
    index = normalized.upper().find(code.upper())
    if index < 0:
        return normalized[:1200]
    return normalized[index:index + 1800]


def _compact_report_text(content: str) -> str:
    text_value = re.sub(r"\s+", "", content or "")
    if not text_value:
        return ""
    ordered_markers = ("（3）调查情况", "调查情况", "破坏", "裂纹", "裂缝", "位移", "挡墙", "整改建议")
    start = 0
    for marker in ordered_markers:
        index = text_value.find(marker)
        if index >= 0:
            start = index
            break
    snippet = text_value[start:start + 760]
    snippet = re.sub(r"（5）附图.*$", "", snippet)
    return snippet


def _brief_report_text(text_value: str) -> str:
    text_value = re.sub(r"\s+", "", text_value or "")
    if not text_value:
        return ""
    level = ""
    level_match = re.search(r"稳定性评价为([^；。]+)", text_value)
    if level_match:
        level = f"稳定性评价为{level_match.group(1)}。"
    point_rules = (
        (r"挡墙与边坡喷锚交接处发生位移，位移宽度为15cm", "挡墙与边坡喷锚交接处发生位移，位移宽度约15cm"),
        (r"喷锚高切坡中部出现混凝土脱落、破碎现象", "喷锚高切坡中部存在混凝土脱落、破碎现象"),
        (r"正屋后墙壁有4条裂纹", "住户房屋正屋后墙壁发现4条裂纹"),
        (r"约有10m长的挡墙发生位移", "上台阶挡墙约10m范围发生位移"),
        (r"格构悬空，格构破损开裂很严重", "格构梁局部悬空，破损开裂较重"),
        (r"屋内墙壁裂纹宽度约为0\.7cm", "居民房屋内墙裂纹宽度约0.7cm"),
        (r"一处横向裂口长8\.5m，宽2cm", "挡墙护坡发现横向裂口，长约8.5m、宽约2cm"),
        (r"护脚墙约有长达70m的破损情况", "护脚墙约70m范围存在破损"),
    )
    points = []
    for pattern, sentence in point_rules:
        if re.search(pattern, text_value):
            points.append(sentence)
        if len(points) >= 4:
            break
    if points:
        return f"{level}主要问题包括：{'；'.join(points)}。"
    return text_value[:160]


def _build_time_text(row: dict) -> str:
    period_text = _format_construction_period(row.get("construction_period"))
    if period_text:
        return f"建设时间为{period_text}"
    start_year = _extract_year(row.get("start_date"))
    finish_year = _extract_year(row.get("finish_date"))
    completion_year = _extract_year(row.get("completion_date"))
    acceptance_year = _extract_year(row.get("acceptance_date"))
    final_acceptance_year = _extract_year(row.get("final_acceptance_date"))

    if start_year and finish_year and start_year != finish_year:
        return f"建设时间为{start_year}年至{finish_year}年"
    if start_year:
        return f"建设时间为{start_year}年"
    if finish_year:
        return f"完工时间为{finish_year}年"
    if completion_year:
        return f"竣工时间为{completion_year}年"
    if acceptance_year:
        return f"验收时间为{acceptance_year}年"
    if final_acceptance_year:
        return f"终验时间为{final_acceptance_year}年"
    return "建设时间在基础资料中未明确记录"


def _format_construction_period(value) -> str:
    text_value = str(value or "").strip()
    if not text_value:
        return ""
    parts = re.split(r"\s*[-—~至]\s*", text_value)
    if len(parts) >= 2:
        start = _format_date_text(parts[0])
        end = _format_date_text(parts[1])
        if start and end:
            return f"{start}至{end}"
    return _format_date_text(text_value) or text_value


def _format_date_text(value: str) -> str:
    text_value = str(value or "").strip()
    match = re.search(r"((?:19|20)\d{2})[./年-](\d{1,2})(?:[./月-](\d{1,2}))?", text_value)
    if not match:
        return ""
    year = match.group(1)
    month = int(match.group(2))
    day = match.group(3)
    if day:
        return f"{year}年{month}月{int(day)}日"
    return f"{year}年{month}月"


def _extract_year(value) -> str:
    text_value = str(value or "").strip()
    if not text_value:
        return ""
    year_match = re.search(r"(19|20)\d{2}", text_value)
    if year_match:
        return year_match.group(0)
    return ""


def _legacy_build_time_text(row: dict) -> str:
    candidates = [
        ("建设时间", row.get("build_date")),
        ("开工时间", row.get("start_date")),
        ("完工时间", row.get("finish_date")),
        ("竣工时间", row.get("completion_date")),
        ("验收时间", row.get("acceptance_date")),
        ("终验时间", row.get("final_acceptance_date")),
    ]
    for label, value in candidates:
        text_value = str(value or "").strip()
        if not text_value:
            continue
        year_match = re.search(r"(19|20)\d{2}", text_value)
        if year_match:
            return f"{label}为{year_match.group(0)}年"
        return f"{label}为{text_value[:10]}"
    return ""


def get_single_slope_visual_assets(question: str) -> tuple[list[str], list[dict], int, list[dict]]:
    code = extract_slope_code(question)
    if not code:
        return [], [], 0, []
    columns, rows, total = get_single_slope_field_status(question)
    attachments = _build_photo_attachments_from_rows(code, rows, max_items=3)
    attachments.extend(_build_displacement_chart_attachment(code))
    return columns, rows, total, attachments


def _build_photo_attachments_from_rows(code: str, rows: list[dict], *, max_items: int = 3) -> list[dict]:
    attachments: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        for field, label in (
            ("photoNo1", "现场照片1"),
            ("photoNo2", "现场照片2"),
            ("photoNo3", "现场照片3"),
            ("crackImageUri", "裂缝照片"),
            ("wallCrackingImageUri", "挡墙/道路开裂照片"),
        ):
            path = str(row.get(field) or "").strip()
            if not path or path in seen:
                continue
            seen.add(path)
            attachments.append({
                "type": "image",
                "label": label,
                "path": path,
                "url": f"/api/photo/file?path={quote(path, safe='')}",
                "source_url": "",
                "hcs_code": code,
                "hcs_name": "",
                "monitoring_id": f"photo-{code}-{len(attachments) + 1}",
                "hcs_id": code,
                "created_on": "",
                "photo_on": "",
            })
            if len(attachments) >= max_items:
                return attachments
    return attachments


def _build_displacement_chart_attachment(code: str) -> list[dict]:
    basic = _fetch_basic(code)
    professional = _fetch_professional(code)
    top_point = professional.get("top_point") if professional else ""
    if not basic or not top_point:
        return []
    engine = _dm_engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
SELECT
  report_year,
  report_month,
  current_x,
  current_y,
  current_h
FROM ai_professional_monitor_monthly_value
WHERE report_year = 2025
  AND UPPER(gqpbh) = :code
  AND monitor_point = :point
ORDER BY report_year ASC, report_month ASC
"""), {"code": code, "point": top_point}).mappings().all()
    finally:
        engine.dispose()
    series = [dict(row) for row in rows]
    if not series:
        return []
    CHART_ROOT.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{code}_{top_point}")
    chart_path = CHART_ROOT / f"{safe_name}.png"
    _build_single_point_png(basic, top_point, series, chart_path)
    return [{
        "type": "image",
        "label": f"监测点{top_point}位移变化曲线图",
        "path": str(chart_path),
        "url": f"{CHART_URL_ROOT}/{chart_path.name}",
        "source_url": "",
        "hcs_code": code,
        "hcs_name": str(basic.get("name") or ""),
        "monitoring_id": f"chart-{code}-{top_point}",
        "hcs_id": code,
        "created_on": "",
        "photo_on": "",
    }]


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _build_single_point_png(basic: dict, point: str, rows: list[dict], output_path: Path) -> None:
    width, height = 1180, 680
    left, right, top, bottom = 92, 48, 132, 92
    plot_w = width - left - right
    plot_h = height - top - bottom
    values = [_to_float(row.get(key)) for row in rows for key in ("current_x", "current_y", "current_h")]
    min_y, max_y = min(values), max(values)
    if min_y == max_y:
        min_y -= 1
        max_y += 1
    span = max_y - min_y
    min_y -= span * 0.18
    max_y += span * 0.18

    def x_at(index: int) -> float:
        return left + (plot_w / max(1, len(rows) - 1)) * index

    def y_at(value: float) -> float:
        return top + (max_y - value) / (max_y - min_y) * plot_h

    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)
    title_font = _font(24, bold=True)
    subtitle_font = _font(15)
    axis_font = _font(13)
    axis_title_font = _font(15, bold=True)
    note_font = _font(15, bold=True)
    legend_font = _font(14)

    draw.rounded_rectangle((18, 18, width - 18, height - 18), radius=10, fill="#ffffff", outline="#dfe6f1", width=1)
    title = f"{basic.get('name') or basic.get('code')}（{basic.get('code')}）{point}位移变化曲线"
    draw.text((36, 50), title, fill="#111827", font=title_font)
    draw.text((36, 82), "2025年X/Y/H三向本期位移变化量，单位：mm", fill="#667085", font=subtitle_font)

    series_def = [
        ("current_x", "X向", "#2563eb"),
        ("current_y", "Y向", "#dc2626"),
        ("current_h", "H向", "#16a34a"),
    ]
    for i, (_, label, color) in enumerate(series_def):
        x = width - 330 + i * 92
        draw.ellipse((x - 6, 78, x + 6, 90), fill=color)
        draw.text((x + 12, 76), label, fill="#344054", font=legend_font)

    draw.rectangle((left, top, left + plot_w, top + plot_h), fill="#f8fafc", outline="#d0d7e2", width=1)
    for i in range(5):
        value = min_y + (max_y - min_y) * i / 4
        y = y_at(value)
        draw.line((left, y, width - right, y), fill="#e6ebf2", width=1)
        label = f"{value:.1f}"
        bbox = draw.textbbox((0, 0), label, font=axis_font)
        draw.text((left - 12 - (bbox[2] - bbox[0]), y - 7), label, fill="#475467", font=axis_font)

    zero_y = y_at(0)
    draw.line((left, zero_y, width - right, zero_y), fill="#64748b", width=2)

    max_abs_item = ("", "", 0.0, 0)
    for key, label, color in series_def:
        coords = []
        for index, row in enumerate(rows):
            value = _to_float(row.get(key))
            coords.append((x_at(index), y_at(value)))
            if abs(value) > abs(max_abs_item[2]):
                max_abs_item = (key, label, value, index)
        if len(coords) >= 2:
            draw.line(coords, fill=color, width=4, joint="curve")
        for x, y in coords:
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=color, outline="#ffffff", width=2)

    step = max(1, len(rows) // 8)
    for index, row in enumerate(rows):
        if index % step != 0 and index != len(rows) - 1:
            continue
        text_label = f"{_safe_int(row.get('report_year'))}-{_safe_int(row.get('report_month')):02d}"
        bbox = draw.textbbox((0, 0), text_label, font=axis_font)
        draw.text((x_at(index) - (bbox[2] - bbox[0]) / 2, height - bottom + 24), text_label, fill="#475467", font=axis_font)

    _, max_label, max_value, max_index = max_abs_item
    max_x = x_at(max_index)
    max_y_pos = y_at(max_value)
    draw.ellipse((max_x - 10, max_y_pos - 10, max_x + 10, max_y_pos + 10), outline="#f97316", width=3)
    note = f"{max_label}变化量相对较大：{max_value:.1f} mm"
    note_x = min(max_x + 16, width - 360)
    draw.text((note_x, max_y_pos - 28), note, fill="#c2410c", font=note_font)

    axis_title = "监测月份"
    bbox = draw.textbbox((0, 0), axis_title, font=axis_title_font)
    draw.text((left + plot_w / 2 - (bbox[2] - bbox[0]) / 2, height - 34), axis_title, fill="#475467", font=axis_title_font)

    y_title = "位移变化量（mm）"
    title_bbox = draw.textbbox((0, 0), y_title, font=axis_title_font)
    label_img = Image.new("RGBA", (title_bbox[2] - title_bbox[0] + 8, title_bbox[3] - title_bbox[1] + 8), (255, 255, 255, 0))
    label_draw = ImageDraw.Draw(label_img)
    label_draw.text((4, 4), y_title, fill="#475467", font=axis_title_font)
    rotated = label_img.rotate(90, expand=True)
    image.paste(rotated, (20, int(top + plot_h / 2 - rotated.height / 2)), rotated)

    image.save(output_path, format="PNG", optimize=True)


def _build_single_point_svg(basic: dict, point: str, rows: list[dict]) -> str:
    width, height = 1180, 680
    left, right, top, bottom = 92, 48, 132, 92
    plot_w = width - left - right
    plot_h = height - top - bottom
    values = [_to_float(row.get(key)) for row in rows for key in ("current_x", "current_y", "current_h")]
    min_y, max_y = min(values), max(values)
    if min_y == max_y:
        min_y -= 1
        max_y += 1
    span = max_y - min_y
    min_y -= span * 0.18
    max_y += span * 0.18

    def x_at(index: int) -> float:
        return left + (plot_w / max(1, len(rows) - 1)) * index

    def y_at(value: float) -> float:
        return top + (max_y - value) / (max_y - min_y) * plot_h

    series_def = [
        ("current_x", "X向", "#2563eb"),
        ("current_y", "Y向", "#dc2626"),
        ("current_h", "H向", "#16a34a"),
    ]
    polylines = []
    points_svg = []
    max_abs_item = ("", "", 0.0, 0)
    for key, label, color in series_def:
        coords = []
        for index, row in enumerate(rows):
            value = _to_float(row.get(key))
            coords.append(f"{x_at(index):.1f},{y_at(value):.1f}")
            if abs(value) > abs(max_abs_item[2]):
                max_abs_item = (key, label, value, index)
        polylines.append(f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>')
        for index, row in enumerate(rows):
            value = _to_float(row.get(key))
            points_svg.append(f'<circle cx="{x_at(index):.1f}" cy="{y_at(value):.1f}" r="4.5" fill="{color}" stroke="#fff" stroke-width="2"/>')

    labels = []
    step = max(1, len(rows) // 8)
    for index, row in enumerate(rows):
        if index % step != 0 and index != len(rows) - 1:
            continue
        text_label = f"{_safe_int(row.get('report_year'))}-{_safe_int(row.get('report_month')):02d}"
        labels.append(f'<text x="{x_at(index):.1f}" y="{height - bottom + 32}" text-anchor="middle" font-size="13" fill="#475467">{escape(text_label)}</text>')

    grid = []
    for i in range(5):
        value = min_y + (max_y - min_y) * i / 4
        y = y_at(value)
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e6ebf2"/>')
        grid.append(f'<text x="{left-12}" y="{y+4:.1f}" text-anchor="end" font-size="13" fill="#475467">{value:.1f}</text>')

    _, max_label, max_value, max_index = max_abs_item
    max_x = x_at(max_index)
    max_y_pos = y_at(max_value)
    title = escape(f"{basic.get('name') or basic.get('code')}（{basic.get('code')}）{point}位移变化曲线")
    subtitle = escape("2025年X/Y/H三向本期位移变化量，单位：mm")
    max_note = escape(f"{max_label}变化量相对较大：{max_value:.1f} mm")
    legend = "".join(
        f'<circle cx="{width - 330 + i * 92}" cy="84" r="6" fill="{color}"/><text x="{width - 318 + i * 92}" y="89" font-size="14" fill="#344054">{label}</text>'
        for i, (_, label, color) in enumerate(series_def)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>text {{ font-family: Arial, "Microsoft YaHei", sans-serif; }}</style>
<rect width="100%" height="100%" fill="#ffffff"/>
<rect x="18" y="18" width="{width-36}" height="{height-36}" rx="10" fill="#fff" stroke="#dfe6f1"/>
<text x="36" y="56" font-size="24" font-weight="700" fill="#111827">{title}</text>
<text x="36" y="88" font-size="15" fill="#667085">{subtitle}</text>
{legend}
<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="#f8fafc" stroke="#d0d7e2"/>
{''.join(grid)}
<line x1="{left}" y1="{y_at(0):.1f}" x2="{width-right}" y2="{y_at(0):.1f}" stroke="#64748b" stroke-width="1.4"/>
{''.join(polylines)}
{''.join(points_svg)}
<circle cx="{max_x:.1f}" cy="{max_y_pos:.1f}" r="10" fill="none" stroke="#f97316" stroke-width="3"/>
<text x="{min(max_x + 16, width - 280):.1f}" y="{max_y_pos - 12:.1f}" font-size="15" font-weight="700" fill="#c2410c">{max_note}</text>
{''.join(labels)}
<text x="28" y="{top + plot_h/2}" transform="rotate(-90 28 {top + plot_h/2})" text-anchor="middle" font-size="15" font-weight="700" fill="#475467">位移变化量（mm）</text>
<text x="{left + plot_w / 2:.1f}" y="{height - 24}" text-anchor="middle" font-size="15" font-weight="700" fill="#475467">监测月份</text>
</svg>"""


def _extract_assessment_level(contents: list[str], code: str) -> str:
    candidates = ("局部不稳定", "基本稳定", "不稳定", "稳定")
    for content in contents:
        normalized = re.sub(r"\s+", "", content or "")
        index = normalized.upper().find(code.upper())
        if index < 0:
            continue
        window = normalized[index:index + 140]
        for candidate in candidates:
            if candidate in window:
                return candidate
        window = normalized[max(0, index - 80):index + 80]
        for candidate in candidates:
            if candidate in window:
                return candidate
    return ""


def _safe_int(value) -> int:
    try:
        return int(float(str(value or 0)))
    except Exception:
        return 0


def _to_float(value) -> float:
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _fmt(value) -> str:
    number = _to_float(value)
    if abs(number - round(number)) < 0.05:
        return str(int(round(number)))
    return f"{number:.1f}"


def _photo_summary(value) -> str:
    count = _safe_int(value)
    return f"已匹配{count}张" if count > 0 else ""
