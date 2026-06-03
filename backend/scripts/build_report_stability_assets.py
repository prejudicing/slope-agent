from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPORT_EXTRACT_DIR = BACKEND_DIR / "report_extract"
OUT_DIR = BACKEND_DIR / "generated" / "report_stability_assets"
BUNDLED_SITE_PACKAGES = Path(
    r"C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages"
)

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if BUNDLED_SITE_PACKAGES.exists() and str(BUNDLED_SITE_PACKAGES) not in sys.path:
    sys.path.append(str(BUNDLED_SITE_PACKAGES))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER  # noqa: E402


SLOPE_CODE_RE = re.compile(r"\b(?:XS|EXS|YL|EYL|BD|EBD|ZG|EZG|420)\d+[A-Z0-9*\-]*\b", re.IGNORECASE)
VALID_SLOPE_CODE_RE = re.compile(r"^(?:XS|EXS|YL|EYL|BD|EBD|ZG|EZG|420)\d", re.IGNORECASE)
PROBLEM_WORDS = ("裂缝", "落石", "掉块", "挡墙开裂", "道路开裂", "坡面破坏", "坡脚破坏", "冲刷", "排水沟堵塞", "隐患", "明显变形", "变形较大", "异常")
STABILITY_WORDS = ("稳定性", "稳定", "较稳定", "基本稳定", "总体稳定", "总体较为稳定", "一般", "较差", "尚无异常", "未见异常")
NEGATIVE_WORDS = ("较差", "一般", "异常", "裂缝", "落石", "掉块", "开裂", "破坏", "堵塞", "冲刷", "隐患", "变形")
STABLE_WORDS = ("总体较为稳定", "总体稳定", "基本稳定", "较稳定", "稳定", "尚无异常", "未见异常", "未见变形及破坏迹象")


@dataclass
class StabilityAsset:
    asset_id: str
    county: str
    report_year: int | None
    report_month: int | None
    report_type: str
    file_hash: str
    file_name: str
    page_no: int | None
    gqpbh: str
    gqpmc: str
    stability_level: str
    stability_text: str
    abnormal_keywords: str
    related_photo_count: int
    photo_urls: str
    thumbnail_urls: str
    source_type: str
    confidence: str
    created_at: str


def dm_engine():
    password = quote_plus(DM_PASSWORD)
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            result.append(json.loads(line))
    return result


def parse_json_list(value) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(str(value))
        if isinstance(data, list):
            return [str(item) for item in data if item]
    except Exception:
        pass
    return []


def compact_text(value: str, limit: int = 900) -> str:
    value = re.sub(r"\s+", "", str(value or ""))
    return value[:limit]


def clean_code(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9\-]", "", str(value or "")).upper()


def is_valid_slope_code(value: str) -> bool:
    return bool(VALID_SLOPE_CODE_RE.match(str(value or "")))


def keyword_hits(text_value: str) -> list[str]:
    hits = []
    stable_context = any(word in text_value for word in ("无异常", "未发现异常", "未见异常", "尚无异常", "未见变形及破坏迹象"))
    for word in PROBLEM_WORDS:
        if word not in text_value:
            continue
        if word == "异常" and stable_context:
            continue
        hits.append(word)
    return hits


def infer_level(text_value: str, keywords: list[str]) -> str:
    if any(word in text_value for word in ("较差", "明显变形", "失稳", "严重")):
        return "需现场复核"
    if any(word in text_value for word in ("无异常", "未发现异常", "未见异常", "尚无异常", "未见变形及破坏迹象", "正常范围内变化")) and not keywords:
        return "总体较稳定"
    if keywords or any(word in text_value for word in ("一般", "异常", "裂缝", "落石", "开裂", "破坏", "堵塞")):
        return "局部异常需跟踪"
    if any(word in text_value for word in STABLE_WORDS):
        return "总体较稳定"
    return "需结合现场复核"


def split_sentences(text_value: str) -> list[str]:
    text_value = compact_text(text_value, 1500)
    pieces = re.split(r"[。；;]", text_value)
    return [piece for piece in pieces if 10 <= len(piece) <= 240]


def is_noise_page(text_value: str) -> bool:
    compact = compact_text(text_value, 500)
    if compact.startswith("目录") and compact.count(".") >= 12:
        return True
    if "目录1概述" in compact and compact.count(".") >= 8:
        return True
    if any(word in compact for word in ("报告名称", "审核：", "校核：", "主要参加人")) and not any(word in compact for word in PROBLEM_WORDS):
        return True
    return False


def is_useful_sentence(sentence: str, code: str = "") -> bool:
    if not sentence:
        return False
    if sentence.count(".") >= 8 or "目录" in sentence[:20]:
        return False
    has_signal = any(word in sentence for word in STABILITY_WORDS + PROBLEM_WORDS)
    if not has_signal:
        return False
    if code and code in clean_code(sentence):
        return True
    return any(word in sentence for word in PROBLEM_WORDS) or any(word in sentence for word in ("总体较为稳定", "总体稳定", "基本稳定", "较稳定", "尚无异常", "未见异常", "未见变形及破坏迹象"))


def extract_name_near_code(text_value: str, code: str) -> str:
    if not text_value or not code:
        return ""
    escaped = re.escape(code)
    patterns = [
        rf"{escaped}\*?\s*([\u4e00-\u9fa5A-Za-z0-9#、\-—（）()]{{2,45}}?高切坡)",
        rf"([\u4e00-\u9fa5A-Za-z0-9#、\-—（）()]{{2,45}}?高切坡)\s*[（(]?\s*{escaped}\*?\s*[）)]?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text_value, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" ，,。；;：:（）()[]【】")
    return ""


def load_name_catalog() -> dict[str, str]:
    engine = dm_engine()
    catalog: dict[str, str] = {}
    try:
        with engine.connect() as conn:
            for table_name, name_col in (
                ("geo_gqp_jbxx", "gqpmc"),
                ("ai_gqp_report_slope_catalog", "report_name"),
            ):
                try:
                    rows = conn.execute(text(f"""
SELECT gqpbh, {name_col} AS name_value
FROM {table_name}
WHERE gqpbh IS NOT NULL AND gqpbh <> ''
""")).mappings().all()
                except Exception:
                    rows = []
                for row in rows:
                    code = clean_code(row.get("gqpbh"))
                    name = str(row.get("name_value") or "").strip()
                    if code and name and code not in catalog:
                        catalog[code] = name
    finally:
        engine.dispose()
    return catalog


def load_photo_assets(year: int | None, min_month: int | None, max_month: int | None) -> list[dict]:
    filters = []
    params = {}
    if year:
        filters.append("report_year = :year")
        params["year"] = year
    if min_month:
        filters.append("report_month >= :min_month")
        params["min_month"] = min_month
    if max_month:
        filters.append("report_month <= :max_month")
        params["max_month"] = max_month
    where = "WHERE " + " AND ".join(filters) if filters else ""
    engine = dm_engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
SELECT county, report_year, report_month, file_hash, file_name, page_no, gqpbh, gqpmc,
       image_url, thumbnail_url, abnormal_keywords, stability_text, confidence
FROM ai_report_photo_asset
{where}
"""), params).mappings().all()
            return [{key: row.get(key) for key in row.keys()} for row in rows]
    finally:
        engine.dispose()


def choose_photos(photos_by_key: dict, file_hash: str, page_no: int | None, gqpbh: str) -> list[dict]:
    candidates = []
    if gqpbh:
        candidates.extend(photos_by_key.get(("slope", gqpbh), []))
    if page_no:
        candidates.extend(photos_by_key.get(("page", file_hash, page_no), []))
    seen = set()
    result = []
    for item in candidates:
        key = item.get("thumbnail_url") or item.get("image_url")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= 3:
            break
    return result


def select_pages(year: int | None, min_month: int | None, max_month: int | None) -> list[dict]:
    pages = load_jsonl(REPORT_EXTRACT_DIR / "report_page_index.jsonl")
    selected = []
    for page in pages:
        page_year = int(page.get("report_year") or 0)
        page_month = int(page.get("report_month") or 0)
        if year and page_year != year:
            continue
        if min_month and page_month < min_month:
            continue
        if max_month and page_month > max_month:
            continue
        text_value = str(page.get("text_excerpt") or "")
        if not text_value:
            continue
        if is_noise_page(text_value):
            continue
        has_signal = any(word in text_value for word in STABILITY_WORDS + PROBLEM_WORDS)
        if has_signal:
            selected.append(page)
    return selected


def build_assets(year: int | None, min_month: int | None, max_month: int | None) -> list[StabilityAsset]:
    pages = select_pages(year, min_month, max_month)
    catalog = load_name_catalog()
    photo_assets = load_photo_assets(year, min_month, max_month)
    photos_by_key: dict[tuple, list[dict]] = defaultdict(list)
    for photo in photo_assets:
        code = clean_code(photo.get("gqpbh"))
        if code:
            photos_by_key[("slope", code)].append(photo)
        if photo.get("file_hash") and photo.get("page_no"):
            photos_by_key[("page", str(photo.get("file_hash")), int(photo.get("page_no")))].append(photo)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    assets: dict[tuple[str, str, int | None], StabilityAsset] = {}
    for page in pages:
        text_value = compact_text(page.get("text_excerpt"), 1200)
        file_hash = str(page.get("file_hash") or "")
        page_no = int(page.get("page_no") or 0) or None
        codes = [clean_code(item) for item in parse_json_list(page.get("slope_codes")) if is_valid_slope_code(item)]
        if not codes:
            codes = [clean_code(match.group(0)) for match in SLOPE_CODE_RE.finditer(text_value)]
        codes = [code for code in codes if code and is_valid_slope_code(code)]
        if not codes and any(word in text_value for word in ("总体较为稳定", "总体稳定", "尚无异常")):
            codes = [""]
        sentences = split_sentences(text_value)
        for code in codes[:12]:
            relevant = []
            for sentence in sentences:
                if is_useful_sentence(sentence, code):
                    relevant.append(sentence)
                if len(relevant) >= 3:
                    break
            if not relevant and code:
                for sentence in sentences:
                    if code in clean_code(sentence) and any(word in sentence for word in PROBLEM_WORDS + STABILITY_WORDS):
                        relevant.append(sentence)
                        break
            if not relevant:
                continue
            stability_text = "；".join(relevant) or text_value[:260]
            keywords = keyword_hits(stability_text)
            photos = choose_photos(photos_by_key, file_hash, page_no, code)
            gqpmc = catalog.get(code, "") or extract_name_near_code(text_value, code)
            asset_id_raw = f"{file_hash}|{page_no}|{code}|{stability_text[:100]}"
            asset_id = hashlib.sha1(asset_id_raw.encode("utf-8", errors="ignore")).hexdigest()[:24]
            key = (file_hash, code, page_no)
            assets[key] = StabilityAsset(
                asset_id=asset_id,
                county=str(page.get("county") or ""),
                report_year=int(page.get("report_year") or 0) or None,
                report_month=int(page.get("report_month") or 0) or None,
                report_type=str(page.get("report_type") or ""),
                file_hash=file_hash,
                file_name=str(page.get("file_name") or ""),
                page_no=page_no,
                gqpbh=code,
                gqpmc=gqpmc,
                stability_level=infer_level(stability_text, keywords),
                stability_text=stability_text,
                abnormal_keywords="、".join(keywords),
                related_photo_count=len(photos),
                photo_urls=json.dumps([photo.get("image_url") for photo in photos if photo.get("image_url")], ensure_ascii=False),
                thumbnail_urls=json.dumps([photo.get("thumbnail_url") for photo in photos if photo.get("thumbnail_url")], ensure_ascii=False),
                source_type="月报页面邻近文字",
                confidence="高" if code and photos else "中" if code or photos else "低",
                created_at=now,
            )
    return sorted(assets.values(), key=lambda item: (item.county, item.report_year or 0, item.report_month or 0, item.file_name, item.page_no or 0, item.gqpbh))


def clean_db_value(value):
    if value is None or isinstance(value, (int, float)):
        return value
    text_value = str(value).replace("\x00", "").strip()
    return text_value.encode("gbk", errors="replace").decode("gbk", errors="replace")


def sync_to_dm(assets: list[StabilityAsset], year: int | None, min_month: int | None, max_month: int | None) -> None:
    engine = dm_engine()
    try:
        with engine.begin() as conn:
            try:
                conn.execute(text("""
CREATE TABLE ai_report_stability_asset (
  asset_id VARCHAR(80) PRIMARY KEY,
  county VARCHAR(50),
  report_year INT,
  report_month INT,
  report_type VARCHAR(80),
  file_hash VARCHAR(128),
  file_name VARCHAR(500),
  page_no INT,
  gqpbh VARCHAR(120),
  gqpmc VARCHAR(500),
  stability_level VARCHAR(80),
  stability_text CLOB,
  abnormal_keywords VARCHAR(500),
  related_photo_count INT,
  photo_urls CLOB,
  thumbnail_urls CLOB,
  source_type VARCHAR(100),
  confidence VARCHAR(20),
  created_at VARCHAR(30)
)
"""))
            except Exception:
                pass
            filters = []
            params = {}
            if year:
                filters.append("report_year = :year")
                params["year"] = year
            if min_month:
                filters.append("report_month >= :min_month")
                params["min_month"] = min_month
            if max_month:
                filters.append("report_month <= :max_month")
                params["max_month"] = max_month
            if filters:
                conn.execute(text("DELETE FROM ai_report_stability_asset WHERE " + " AND ".join(filters)), params)
            else:
                conn.execute(text("DELETE FROM ai_report_stability_asset"))
            insert_sql = text("""
INSERT INTO ai_report_stability_asset (
  asset_id, county, report_year, report_month, report_type, file_hash, file_name,
  page_no, gqpbh, gqpmc, stability_level, stability_text, abnormal_keywords,
  related_photo_count, photo_urls, thumbnail_urls, source_type, confidence, created_at
) VALUES (
  :asset_id, :county, :report_year, :report_month, :report_type, :file_hash, :file_name,
  :page_no, :gqpbh, :gqpmc, :stability_level, :stability_text, :abnormal_keywords,
  :related_photo_count, :photo_urls, :thumbnail_urls, :source_type, :confidence, :created_at
)
""")
            for asset in assets:
                row = {key: clean_db_value(value) for key, value in asdict(asset).items()}
                conn.execute(insert_sql, row)
    finally:
        engine.dispose()


def write_outputs(assets: list[StabilityAsset]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "report_stability_assets.json").write_text(
        json.dumps([asdict(item) for item in assets], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    by_county = defaultdict(lambda: {"count": 0, "with_photo": 0, "local_problem": 0})
    for item in assets:
        row = by_county[item.county]
        row["count"] += 1
        if item.related_photo_count:
            row["with_photo"] += 1
        if item.stability_level != "总体较稳定":
            row["local_problem"] += 1
    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "asset_count": len(assets),
        "by_county": dict(by_county),
    }
    (OUT_DIR / "report_stability_assets_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=0)
    parser.add_argument("--min-month", type=int, default=0)
    parser.add_argument("--max-month", type=int, default=0)
    parser.add_argument("--sync-db", action="store_true")
    args = parser.parse_args()
    year = args.year or None
    min_month = args.min_month or None
    max_month = args.max_month or None
    assets = build_assets(year, min_month, max_month)
    write_outputs(assets)
    if args.sync_db:
        sync_to_dm(assets, year, min_month, max_month)
    print(json.dumps({
        "asset_count": len(assets),
        "summary": str(OUT_DIR / "report_stability_assets_summary.json"),
        "synced_db": bool(args.sync_db),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
