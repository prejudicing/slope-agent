"""现场照片路径补充与文件代理。

主业务查询仍以达梦库结果为准；当用户明确需要照片/图片/视频时，
这里用查询结果里的高切坡编号去 SQL Server 照片库补充附件路径。
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Iterable
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from sqlalchemy import bindparam, text

from app.config import PHOTO_DOWNLOAD_TIMEOUT, PHOTO_FILE_BASE_URL
from app.db import get_photo_sqlalchemy_engine


PHOTO_INTENT_KEYWORDS = (
    "照片",
    "图片",
    "现场图",
    "现场照片",
    "影像",
    "视频",
)
CODE_COLUMNS = (
    "gqpbh",
    "gqp_no",
    "xmbh",
    "code",
    "高切坡编号",
    "编号",
    "项目编号",
    "边坡编号",
)
PHOTO_FIELDS = (
    ("photoNo1", "现场照片1", "image"),
    ("photoNo2", "现场照片2", "image"),
    ("photoNo3", "现场照片3", "image"),
    ("crackImageUri", "裂缝照片", "image"),
    ("wallCrackingImageUri", "挡墙/道路开裂照片", "image"),
    ("video", "现场视频", "video"),
)
YEAR_RE = re.compile(r"(20\d{2})\s*年?")
ABNORMAL_KEYWORDS = (
    "异常",
    "裂缝",
    "裂痕",
    "落石",
    "破坏",
    "开裂",
    "堵塞",
    "风险",
)


def has_photo_intent(question: str) -> bool:
    compact = "".join((question or "").split())
    return any(keyword in compact for keyword in PHOTO_INTENT_KEYWORDS)


def _extract_year(question: str) -> int | None:
    match = YEAR_RE.search(question or "")
    if not match:
        return None
    return int(match.group(1))


def _has_abnormal_intent(question: str) -> bool:
    compact = "".join((question or "").split())
    return any(keyword in compact for keyword in ABNORMAL_KEYWORDS)


def _stringify(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _extract_codes(rows: list[dict]) -> list[str]:
    codes: list[str] = []
    seen = set()
    for row in rows:
        by_lower = {str(key).lower(): value for key, value in row.items()}
        for column in CODE_COLUMNS:
            value = row.get(column)
            if value is None:
                value = by_lower.get(column.lower())
            code = _stringify(value)
            if not code or code in seen:
                continue
            seen.add(code)
            codes.append(code)
    return codes


def _build_file_url(path: str) -> str:
    quoted_path = quote(path, safe="")
    return f"/api/photo/file?path={quoted_path}"


def _build_source_url(path: str) -> str:
    if not PHOTO_FILE_BASE_URL:
        return ""
    return urljoin(f"{PHOTO_FILE_BASE_URL}/", path.lstrip("/"))


def _serialize_dt(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return _stringify(value)


def _iter_photo_attachments(row) -> Iterable[dict]:
    for field_name, label, media_type in PHOTO_FIELDS:
        path = _stringify(getattr(row, field_name))
        if not path:
            continue
        yield {
            "type": media_type,
            "label": label,
            "path": path,
            "url": _build_file_url(path),
            "source_url": _build_source_url(path),
            "hcs_code": _stringify(row.hcs_code),
            "hcs_name": _stringify(row.hcs_name),
            "monitoring_id": _stringify(row.monitoring_id),
            "hcs_id": _stringify(row.hcs_id),
            "created_on": _serialize_dt(row.createdOn),
            "photo_on": _serialize_dt(row.photoOn),
        }


def _row_to_display(row) -> dict:
    photo_paths = [
        _stringify(getattr(row, field_name))
        for field_name, _, media_type in PHOTO_FIELDS
        if media_type == "image"
    ]
    video_paths = [
        _stringify(getattr(row, field_name))
        for field_name, _, media_type in PHOTO_FIELDS
        if media_type == "video"
    ]
    photo_paths = [path for path in photo_paths if path]
    video_paths = [path for path in video_paths if path]
    return {
        "高切坡编号": _stringify(row.hcs_code),
        "高切坡名称": _stringify(row.hcs_name),
        "监测记录ID": _stringify(row.monitoring_id),
        "监测时间": _serialize_dt(row.createdOn),
        "拍照时间": _serialize_dt(row.photoOn),
        "总体异常": _stringify(row.overallSituation),
        "裂缝": _stringify(row.isCrack),
        "坡面破坏": _stringify(row.slopeFailure),
        "挡墙或道路开裂": _stringify(row.wallCracking),
        "坡周乱搭乱堆": _stringify(row.disorderlyPush),
        "监测设施异常": _stringify(row.facilities),
        "照片数量": str(len(photo_paths)),
        "视频数量": str(len(video_paths)),
    }


def search_photo_records(
    question: str,
    *,
    max_records: int = 80,
    max_attachments: int = 120,
) -> dict:
    """直接从 SQL Server 照片库查询照片类问题。"""
    if not has_photo_intent(question):
        return {
            "columns": [],
            "rows": [],
            "total_rows": 0,
            "attachments": [],
            "sql": "",
        }

    year = _extract_year(question)
    has_abnormal = _has_abnormal_intent(question)
    where_parts = [
        "("
        "m.photoNo1 IS NOT NULL OR "
        "m.photoNo2 IS NOT NULL OR "
        "m.photoNo3 IS NOT NULL OR "
        "m.crackImageUri IS NOT NULL OR "
        "m.wallCrackingImageUri IS NOT NULL OR "
        "m.video IS NOT NULL"
        ")"
    ]
    params: dict[str, object] = {"limit": max_records}

    if year:
        where_parts.append("COALESCE(m.photoOn, m.createdOn) >= :start_time")
        where_parts.append("COALESCE(m.photoOn, m.createdOn) < :end_time")
        params["start_time"] = datetime(year, 1, 1)
        params["end_time"] = datetime(year + 1, 1, 1)

    if has_abnormal:
        where_parts.append(
            "("
            "m.overallSituation = 1 OR "
            "m.isCrack = 1 OR "
            "m.slopeFailure = 1 OR "
            "m.wallCracking = 1 OR "
            "m.disorderlyPush = 1 OR "
            "m.facilities = 1 OR "
            "m.hcSlopeStatus = 1 OR "
            "m.crackImageUri IS NOT NULL OR "
            "m.wallCrackingImageUri IS NOT NULL"
            ")"
        )

    where_sql = " AND ".join(where_parts)
    sql_text = f"""
SELECT TOP {max_records}
  s.code AS hcs_code,
  s.name AS hcs_name,
  m.id AS monitoring_id,
  m.hcs_id,
  m.createdOn,
  m.photoOn,
  m.overallSituation,
  m.isCrack,
  m.slopeFailure,
  m.wallCracking,
  m.disorderlyPush,
  m.facilities,
  m.photoNo1,
  m.photoNo2,
  m.photoNo3,
  m.crackImageUri,
  m.wallCrackingImageUri,
  m.video
FROM tb_hcs_monitoring m
JOIN tb_hcslope s ON m.hcs_id = s.id
WHERE {where_sql}
ORDER BY COALESCE(m.photoOn, m.createdOn) DESC, m.id DESC
""".strip()

    count_sql = text(
        f"""
SELECT COUNT(*) AS total_count
FROM tb_hcs_monitoring m
JOIN tb_hcslope s ON m.hcs_id = s.id
WHERE {where_sql}
"""
    )

    columns = [
        "高切坡编号",
        "高切坡名称",
        "监测记录ID",
        "监测时间",
        "拍照时间",
        "总体异常",
        "裂缝",
        "坡面破坏",
        "挡墙或道路开裂",
        "坡周乱搭乱堆",
        "监测设施异常",
        "照片数量",
        "视频数量",
    ]
    display_rows: list[dict] = []
    attachments: list[dict] = []
    total_rows = 0

    engine = get_photo_sqlalchemy_engine()
    try:
        with engine.connect() as conn:
            total_rows = int(conn.execute(count_sql, params).scalar() or 0)
            result = conn.execute(text(sql_text), params)
            for row in result:
                display_rows.append(_row_to_display(row))
                attachments.extend(_iter_photo_attachments(row))
                if len(attachments) >= max_attachments:
                    attachments = attachments[:max_attachments]
    finally:
        engine.dispose()

    return {
        "columns": columns,
        "rows": display_rows,
        "total_rows": total_rows,
        "attachments": attachments,
        "sql": sql_text,
    }


def build_photo_summary(question: str, payload: dict) -> str:
    total_rows = int(payload.get("total_rows") or 0)
    attachments = payload.get("attachments") or []
    if total_rows <= 0:
        return "未查询到符合条件的现场照片记录。可以调整年份、异常条件或高切坡编号后重试。"
    return (
        f"已查询到符合“{question}”的现场照片记录 {total_rows} 条，"
        f"当前返回 {len(payload.get('rows') or [])} 条记录，"
        f"并整理出 {len(attachments)} 个照片/视频附件。"
    )


def find_photo_attachments(
    question: str,
    rows: list[dict],
    *,
    max_codes: int = 20,
    max_attachments: int = 30,
) -> list[dict]:
    """按主查询结果中的高切坡编号补充现场照片附件。"""
    if not has_photo_intent(question) or not rows:
        return []

    codes = _extract_codes(rows)[:max_codes]
    if not codes:
        return []

    sql = (
        text(
            """
            SELECT TOP 200
              s.code AS hcs_code,
              s.name AS hcs_name,
              m.id AS monitoring_id,
              m.hcs_id,
              m.createdOn,
              m.photoOn,
              m.photoNo1,
              m.photoNo2,
              m.photoNo3,
              m.crackImageUri,
              m.wallCrackingImageUri,
              m.video
            FROM tb_hcs_monitoring m
            JOIN tb_hcslope s ON m.hcs_id = s.id
            WHERE s.code IN :codes
              AND (
                m.photoNo1 IS NOT NULL OR
                m.photoNo2 IS NOT NULL OR
                m.photoNo3 IS NOT NULL OR
                m.crackImageUri IS NOT NULL OR
                m.wallCrackingImageUri IS NOT NULL OR
                m.video IS NOT NULL
              )
            ORDER BY COALESCE(m.photoOn, m.createdOn) DESC, m.id DESC
            """
        )
        .bindparams(bindparam("codes", expanding=True))
    )

    attachments: list[dict] = []
    engine = get_photo_sqlalchemy_engine()
    try:
        with engine.connect() as conn:
            result = conn.execute(sql, {"codes": codes})
            for row in result:
                attachments.extend(_iter_photo_attachments(row))
                if len(attachments) >= max_attachments:
                    return attachments[:max_attachments]
    finally:
        engine.dispose()

    return attachments[:max_attachments]


def download_photo_file(path: str) -> tuple[bytes, str]:
    """从文件服务器下载照片/视频二进制。"""
    if not PHOTO_FILE_BASE_URL:
        raise RuntimeError("未配置 PHOTO_FILE_BASE_URL，无法代理下载现场照片。")
    if not path or "://" in path or path.startswith("//") or ".." in path:
        raise RuntimeError("非法文件路径。")

    source_url = _build_source_url(path)
    request = Request(source_url, headers={"User-Agent": "hcs-agent/1.0"})
    with urlopen(request, timeout=PHOTO_DOWNLOAD_TIMEOUT) as response:
        content_type = response.headers.get("Content-Type") or "application/octet-stream"
        return response.read(), content_type
