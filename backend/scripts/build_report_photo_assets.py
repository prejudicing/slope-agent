from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPORT_EXTRACT_DIR = BACKEND_DIR / "report_extract"
OUT_ROOT = BACKEND_DIR / "generated" / "report_photos"
BUNDLED_SITE_PACKAGES = Path(
    r"C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages"
)

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if BUNDLED_SITE_PACKAGES.exists() and str(BUNDLED_SITE_PACKAGES) not in sys.path:
    sys.path.append(str(BUNDLED_SITE_PACKAGES))

from PIL import Image, ImageOps  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER  # noqa: E402


PHOTO_WORDS = ("照片", "现场照片", "巡视照片", "巡查照片", "现场图片", "影像", "图片", "全景")
PROBLEM_WORDS = ("裂缝", "落石", "掉块", "挡墙开裂", "道路开裂", "坡面破坏", "冲刷", "排水", "隐患", "异常", "变形")
STABILITY_WORDS = ("稳定性", "稳定", "较稳定", "基本稳定", "总体稳定", "一般", "较差")
SLOPE_CODE_RE = re.compile(r"\b(?:XS|EXS|YL|EYL|BD|EBD|ZG|EZG|420)\d+[A-Z0-9*\-]*\b", re.IGNORECASE)
MONITOR_POINT_RE = re.compile(r"\b(?:XS|XST|YL|BD|BDGPS|BDTPS|ZG|ZX|ZXT)?JC\d+[A-Z0-9\-]*\b", re.IGNORECASE)
VALID_SLOPE_CODE_RE = re.compile(r"^(?:XS|EXS|YL|EYL|BD|EBD|ZG|EZG|420)\d", re.IGNORECASE)


@dataclass
class PhotoAsset:
    asset_id: str
    county: str
    report_year: int | None
    report_month: int | None
    report_type: str
    file_hash: str
    file_name: str
    page_no: int | None
    image_index: int
    gqpbh: str
    gqpmc: str
    monitor_point: str
    photo_type: str
    abnormal_keywords: str
    stability_text: str
    nearby_text: str
    original_path: str
    image_path: str
    thumbnail_path: str
    original_url: str
    image_url: str
    thumbnail_url: str
    width: int
    height: int
    original_size_kb: int
    image_size_kb: int
    thumbnail_size_kb: int
    confidence: str
    created_at: str


def dm_engine():
    password = quote_plus(DM_PASSWORD)
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def fetch_report_docs() -> dict[str, dict]:
    engine = dm_engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
SELECT file_hash, file_name, file_path, county, report_year, report_month, report_type
FROM ai_monthly_report_doc
WHERE parse_status = 'ok'
""")).mappings().all()
            return {str(row["file_hash"]): {key: row.get(key) for key in row.keys()} for row in rows}
    finally:
        engine.dispose()


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            result.append(json.loads(line))
    return result


def compact_text(value: str, limit: int = 900) -> str:
    value = re.sub(r"\s+", "", str(value or ""))
    return value[:limit]


def keyword_hits(text_value: str, words: tuple[str, ...]) -> list[str]:
    return [word for word in words if word in text_value]


def parse_json_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    try:
        data = json.loads(str(value))
        if isinstance(data, list):
            return [str(item) for item in data if item]
    except Exception:
        pass
    return []


def is_valid_slope_code(value: str) -> bool:
    return bool(VALID_SLOPE_CODE_RE.match(str(value or "")))


def infer_photo_type(text_value: str) -> str:
    if any(word in text_value for word in ("宏观巡视", "巡视照片", "巡查照片")):
        return "宏观巡视照片"
    if any(word in text_value for word in ("裂缝", "挡墙开裂", "道路开裂")):
        return "裂缝/开裂照片"
    if any(word in text_value for word in ("落石", "掉块", "坡面破坏")):
        return "落石/坡面破坏照片"
    return "现场照片"


def extract_stability_text(text_value: str) -> str:
    pieces = re.split(r"[。；;]", re.sub(r"\s+", "", text_value or ""))
    selected = []
    for piece in pieces:
        if 16 <= len(piece) <= 180 and any(word in piece for word in STABILITY_WORDS + PROBLEM_WORDS):
            selected.append(piece)
        if len(selected) >= 2:
            break
    return "；".join(selected)


def select_photo_pages(
    max_pages: int = 0,
    year: int | None = None,
    min_month: int | None = None,
    max_month: int | None = None,
) -> list[dict]:
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
        has_photo = page.get("asset_type") == "现场照片/图片" or any(word in text_value for word in PHOTO_WORDS)
        has_business_signal = (
            int(page.get("risk_score") or 0) > 0
            or any(word in text_value for word in PROBLEM_WORDS)
            or any(word in text_value for word in STABILITY_WORDS)
        )
        if page.get("asset_type") == "现场照片/图片":
            has_business_signal = True
        if has_photo and has_business_signal and int(page.get("image_count") or 0) > 0:
            selected.append(page)
    selected.sort(
        key=lambda item: (
            str(item.get("county") or ""),
            int(item.get("report_year") or 0),
            int(item.get("report_month") or 0),
            str(item.get("file_name") or ""),
            int(item.get("page_no") or 0),
        )
    )
    return selected[:max_pages] if max_pages and max_pages > 0 else selected


def safe_name(value: str, fallback: str = "item") -> str:
    value = str(value or "").strip()
    value = re.sub(r"[\\/:*?\"<>|\s]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return (value or fallback)[:90]


def output_dirs(county: str, year: int | None, month: int | None) -> tuple[Path, Path, Path]:
    year_part = f"{year:04d}" if year else "unknown_year"
    month_part = f"{year:04d}-{month:02d}" if year and month else "unknown_month"
    base = OUT_ROOT / year_part / safe_name(county, "未识别") / month_part
    original = base / "original"
    preview = base / "preview"
    thumb = base / "thumb"
    original.mkdir(parents=True, exist_ok=True)
    preview.mkdir(parents=True, exist_ok=True)
    thumb.mkdir(parents=True, exist_ok=True)
    return original, preview, thumb


def asset_url(path: Path) -> str:
    rel = path.relative_to(BACKEND_DIR / "generated").as_posix()
    return f"/report-assets/{rel}"


def normalize_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    elif image.mode == "L":
        image = image.convert("RGB")
    return image


def resize_for_width(image: Image.Image, max_width: int) -> Image.Image:
    if image.width <= max_width:
        return image.copy()
    height = int(image.height * (max_width / image.width))
    return image.resize((max_width, height), Image.Resampling.LANCZOS)


def save_compressed(image: Image.Image, path: Path, max_width: int, quality: int) -> None:
    resized = resize_for_width(image, max_width)
    resized.save(path, format="JPEG", quality=quality, optimize=True, progressive=True)


def image_size_kb(path: Path) -> int:
    try:
        return int(path.stat().st_size / 1024)
    except Exception:
        return 0


def build_asset_id(file_hash: str, page_no: int | None, image_index: int, gqpbh: str, text_value: str) -> str:
    raw = f"{file_hash}|{page_no}|{image_index}|{gqpbh}|{text_value[:80]}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]


def resolve_name_from_db(gqpbh: str) -> str:
    if not gqpbh:
        return ""
    lookup_code = re.sub(r"[^A-Za-z0-9\-]", "", gqpbh).upper()
    engine = dm_engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
SELECT gqpmc
FROM geo_gqp_jbxx
WHERE UPPER(gqpbh) = :gqpbh
FETCH FIRST 1 ROWS ONLY
"""), {"gqpbh": lookup_code}).mappings().first()
            return str(row["gqpmc"]) if row and row.get("gqpmc") else ""
    except Exception:
        return ""
    finally:
        engine.dispose()


def infer_name_near_code(text_value: str, gqpbh: str) -> str:
    if not text_value or not gqpbh:
        return ""
    code = re.escape(gqpbh)
    patterns = [
        rf"{code}\*?\s*([\u4e00-\u9fa5A-Za-z0-9#、\-—（）()]{{2,45}}?高切坡)",
        rf"([\u4e00-\u9fa5A-Za-z0-9#、\-—（）()]{{2,45}}?高切坡)\s*[（(]?\s*{code}\*?\s*[）)]?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text_value, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" ，,。；;：:（）()[]【】")
    return ""


def make_photo_asset(page: dict, doc: dict, image: Image.Image, image_index: int, force: bool = False) -> PhotoAsset | None:
    county = str(doc.get("county") or page.get("county") or "未识别")
    year = int(doc.get("report_year") or page.get("report_year") or 0) or None
    month = int(doc.get("report_month") or page.get("report_month") or 0) or None
    file_hash = str(doc.get("file_hash") or page.get("file_hash") or "")
    file_name = str(doc.get("file_name") or page.get("file_name") or "")
    page_no = int(page.get("page_no") or 0) or None
    nearby_text = compact_text(page.get("text_excerpt"), 900)
    slope_codes = parse_json_list(page.get("slope_codes"))
    monitor_points = parse_json_list(page.get("monitor_points"))
    slope_codes = [code for code in slope_codes if is_valid_slope_code(code)]
    if not slope_codes:
        slope_codes = [match.group(0) for match in SLOPE_CODE_RE.finditer(nearby_text)]
    if not monitor_points:
        monitor_points = [match.group(0) for match in MONITOR_POINT_RE.finditer(nearby_text)]
    gqpbh = slope_codes[min(image_index - 1, len(slope_codes) - 1)] if slope_codes else ""
    gqpbh = re.sub(r"[^A-Za-z0-9\-]", "", gqpbh).upper()
    monitor_point = monitor_points[min(image_index - 1, len(monitor_points) - 1)] if monitor_points else ""
    gqpmc = resolve_name_from_db(gqpbh) or infer_name_near_code(nearby_text, gqpbh)
    keywords = keyword_hits(nearby_text, PROBLEM_WORDS)
    stability_text = extract_stability_text(nearby_text)
    photo_type = infer_photo_type(nearby_text)
    confidence = "高" if gqpbh and keywords else "中" if gqpbh or keywords else "低"
    asset_id = build_asset_id(file_hash, page_no, image_index, gqpbh, nearby_text)

    original_dir, preview_dir, thumb_dir = output_dirs(county, year, month)
    stem_parts = [
        safe_name(gqpbh or "unmatched"),
        f"p{page_no or 0:03d}",
        f"img{image_index:02d}",
        asset_id[:8],
    ]
    stem = "_".join(stem_parts)
    original_path = original_dir / f"{stem}.jpg"
    image_path = preview_dir / f"{stem}.jpg"
    thumb_path = thumb_dir / f"{stem}.jpg"
    normalized = normalize_image(image)
    if force or not (original_path.exists() and image_path.exists() and thumb_path.exists()):
        save_compressed(normalized, original_path, 2200, 86)
        save_compressed(normalized, image_path, 1200, 80)
        save_compressed(normalized, thumb_path, 420, 76)

    return PhotoAsset(
        asset_id=asset_id,
        county=county,
        report_year=year,
        report_month=month,
        report_type=str(doc.get("report_type") or page.get("report_type") or ""),
        file_hash=file_hash,
        file_name=file_name,
        page_no=page_no,
        image_index=image_index,
        gqpbh=gqpbh,
        gqpmc=gqpmc,
        monitor_point=monitor_point,
        photo_type=photo_type,
        abnormal_keywords="、".join(keywords),
        stability_text=stability_text,
        nearby_text=nearby_text,
        original_path=str(original_path),
        image_path=str(image_path),
        thumbnail_path=str(thumb_path),
        original_url=asset_url(original_path),
        image_url=asset_url(image_path),
        thumbnail_url=asset_url(thumb_path),
        width=normalized.width,
        height=normalized.height,
        original_size_kb=image_size_kb(original_path),
        image_size_kb=image_size_kb(image_path),
        thumbnail_size_kb=image_size_kb(thumb_path),
        confidence=confidence,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def extract_pdf_page_images(path: Path, page_no: int) -> list[Image.Image]:
    reader = PdfReader(str(path))
    if page_no < 1 or page_no > len(reader.pages):
        return []
    page = reader.pages[page_no - 1]
    images = []
    try:
        page_images = list(page.images)
    except Exception:
        page_images = []
    for image_file in page_images:
        try:
            image = image_file.image
            image.load()
            images.append(image)
        except Exception:
            continue
    return images


def docx_units_with_images(path: Path) -> list[dict]:
    ns = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        if "word/document.xml" not in names:
            return []
        rel_map: dict[str, str] = {}
        if "word/_rels/document.xml.rels" in names:
            rel_root = ET.fromstring(zf.read("word/_rels/document.xml.rels"))
            for rel in rel_root.findall(".//rel:Relationship", ns):
                rid = rel.attrib.get("Id", "")
                target = rel.attrib.get("Target", "")
                if rid and target:
                    rel_map[rid] = "word/" + target.lstrip("/")
        root = ET.fromstring(zf.read("word/document.xml"))
        body = root.find("w:body", ns)
        units = []
        if body is None:
            return []
        for child in list(body):
            if child.tag.endswith("}p"):
                line = "".join(t.text or "" for t in child.findall(".//w:t", ns)).strip()
                image_names = []
                for node in child.findall(".//a:blip", ns):
                    rid = node.attrib.get(f"{{{ns['r']}}}embed", "")
                    image_name = rel_map.get(rid, "")
                    if image_name:
                        image_names.append(image_name)
                if line or image_names:
                    units.append({"text": line, "images": image_names})
            elif child.tag.endswith("}tbl"):
                cell_text = "".join(t.text or "" for t in child.findall(".//w:t", ns)).strip()
                units.append({"text": cell_text[:1200], "images": []})
        return units


def extract_docx_page_images(path: Path, page_no: int) -> list[Image.Image]:
    units = docx_units_with_images(path)
    start = (page_no - 1) * 18
    end = page_no * 18
    image_names = []
    for unit in units[start:end]:
        image_names.extend(unit.get("images") or [])
    images = []
    with zipfile.ZipFile(path) as zf:
        for name in image_names:
            if name not in zf.namelist():
                continue
            try:
                image = Image.open(BytesIO(zf.read(name)))
                image.load()
                images.append(image)
            except Exception:
                continue
    return images


def extract_assets(
    max_pages: int = 0,
    force: bool = False,
    year: int | None = None,
    min_month: int | None = None,
    max_month: int | None = None,
) -> list[PhotoAsset]:
    docs = fetch_report_docs()
    pages = select_photo_pages(
        max_pages=max_pages,
        year=year,
        min_month=min_month,
        max_month=max_month,
    )
    assets: list[PhotoAsset] = []
    for page in pages:
        file_hash = str(page.get("file_hash") or "")
        doc = docs.get(file_hash)
        if not doc:
            continue
        source = Path(str(doc.get("file_path") or ""))
        if not source.exists():
            continue
        page_no = int(page.get("page_no") or 0)
        if source.suffix.lower() == ".pdf":
            images = extract_pdf_page_images(source, page_no)
        elif source.suffix.lower() == ".docx":
            images = extract_docx_page_images(source, page_no)
        else:
            images = []
        for index, image in enumerate(images, start=1):
            if image.width < 120 or image.height < 100:
                continue
            asset = make_photo_asset(page, doc, image, index, force=force)
            if asset:
                assets.append(asset)
    return assets


def clean_db_value(value):
    if value is None or isinstance(value, (int, float)):
        return value
    text_value = str(value).replace("\x00", "").strip()
    return text_value.encode("gbk", errors="replace").decode("gbk", errors="replace")


def sync_to_dm(assets: list[PhotoAsset]) -> None:
    engine = dm_engine()
    try:
        with engine.begin() as conn:
            try:
                conn.execute(text("""
CREATE TABLE ai_report_photo_asset (
  asset_id VARCHAR(80) PRIMARY KEY,
  county VARCHAR(50),
  report_year INT,
  report_month INT,
  report_type VARCHAR(80),
  file_hash VARCHAR(128),
  file_name VARCHAR(500),
  page_no INT,
  image_index INT,
  gqpbh VARCHAR(120),
  gqpmc VARCHAR(500),
  monitor_point VARCHAR(120),
  photo_type VARCHAR(100),
  abnormal_keywords VARCHAR(500),
  stability_text CLOB,
  nearby_text CLOB,
  original_path VARCHAR(1000),
  image_path VARCHAR(1000),
  thumbnail_path VARCHAR(1000),
  original_url VARCHAR(1000),
  image_url VARCHAR(1000),
  thumbnail_url VARCHAR(1000),
  width INT,
  height INT,
  original_size_kb INT,
  image_size_kb INT,
  thumbnail_size_kb INT,
  confidence VARCHAR(20),
  created_at VARCHAR(30)
)
"""))
            except Exception:
                pass
            if assets:
                hashes = sorted({asset.file_hash for asset in assets if asset.file_hash})
                for file_hash in hashes:
                    conn.execute(text("DELETE FROM ai_report_photo_asset WHERE file_hash = :file_hash"), {"file_hash": file_hash})
            insert_sql = text("""
INSERT INTO ai_report_photo_asset (
  asset_id, county, report_year, report_month, report_type, file_hash, file_name,
  page_no, image_index, gqpbh, gqpmc, monitor_point, photo_type, abnormal_keywords,
  stability_text, nearby_text, original_path, image_path, thumbnail_path,
  original_url, image_url, thumbnail_url, width, height, original_size_kb,
  image_size_kb, thumbnail_size_kb, confidence, created_at
) VALUES (
  :asset_id, :county, :report_year, :report_month, :report_type, :file_hash, :file_name,
  :page_no, :image_index, :gqpbh, :gqpmc, :monitor_point, :photo_type, :abnormal_keywords,
  :stability_text, :nearby_text, :original_path, :image_path, :thumbnail_path,
  :original_url, :image_url, :thumbnail_url, :width, :height, :original_size_kb,
  :image_size_kb, :thumbnail_size_kb, :confidence, :created_at
)
""")
            for asset in assets:
                row = {key: clean_db_value(value) for key, value in asdict(asset).items()}
                conn.execute(insert_sql, row)
    finally:
        engine.dispose()


def write_outputs(assets: list[PhotoAsset]) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    payload = [asdict(asset) for asset in assets]
    (OUT_ROOT / "report_photo_assets.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    by_county: dict[str, dict] = {}
    for asset in assets:
        item = by_county.setdefault(asset.county, {"count": 0, "thumbnail_kb": 0, "preview_kb": 0, "original_kb": 0})
        item["count"] += 1
        item["thumbnail_kb"] += asset.thumbnail_size_kb
        item["preview_kb"] += asset.image_size_kb
        item["original_kb"] += asset.original_size_kb
    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "asset_count": len(assets),
        "by_county": by_county,
        "storage_note": "数据库仅保存索引和URL；图片文件按original/preview/thumb三档保存，页面默认加载缩略图。",
    }
    (OUT_ROOT / "report_photo_assets_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=0, help="最多处理多少个候选页；0表示全部")
    parser.add_argument("--year", type=int, default=0, help="只处理指定年份；0表示不限")
    parser.add_argument("--min-month", type=int, default=0, help="只处理该月份及之后；0表示不限")
    parser.add_argument("--max-month", type=int, default=0, help="只处理该月份及之前；0表示不限")
    parser.add_argument("--force", action="store_true", help="强制重新生成图片")
    parser.add_argument("--sync-db", action="store_true", help="同步写入达梦索引表")
    args = parser.parse_args()

    assets = extract_assets(
        max_pages=args.max_pages,
        force=args.force,
        year=args.year or None,
        min_month=args.min_month or None,
        max_month=args.max_month or None,
    )
    write_outputs(assets)
    if args.sync_db:
        sync_to_dm(assets)
    summary_path = OUT_ROOT / "report_photo_assets_summary.json"
    print(json.dumps({
        "asset_count": len(assets),
        "summary": str(summary_path),
        "synced_db": bool(args.sync_db),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
