from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
DOC_DIR = PROJECT_DIR.parent / "doc"
OUT_DIR = BACKEND_DIR / "report_extract"
BUNDLED_SITE_PACKAGES = Path(
    r"C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages"
)
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if BUNDLED_SITE_PACKAGES.exists() and str(BUNDLED_SITE_PACKAGES) not in sys.path:
    sys.path.append(str(BUNDLED_SITE_PACKAGES))


COUNTIES = ["巴东县", "兴山县", "夷陵区", "秭归县"]
CHART_WORDS = [
    "折线图",
    "曲线",
    "累计位移",
    "本期位移",
    "位移变化",
    "监测点",
    "测点",
    "降雨量",
    "库水位",
    "水位",
    "变形曲线",
    "过程线",
]
PHOTO_WORDS = ["照片", "现场照片", "现场图片", "影像", "图片", "无人机", "全景", "巡查照片"]
TABLE_WORDS = ["统计表", "监测数据", "巡查记录", "汇总表", "一览表", "观测成果", "监测成果"]
RISK_WORDS = ["异常", "预警", "裂缝", "变形", "风险", "处置", "稳定性", "隐患", "告警"]


@dataclass
class ReportDocIndex:
    file_hash: str
    file_name: str
    file_path: str
    file_ext: str
    file_size: int
    county: str
    report_year: int | None
    report_month: int | None
    report_type: str
    title: str
    text_length: int
    page_count: int | None
    image_count: int
    table_count: int
    chart_page_count: int
    photo_page_count: int
    table_page_count: int
    parse_status: str
    parse_message: str
    analyzed_at: str


@dataclass
class ReportPageIndex:
    page_id: str
    file_hash: str
    file_name: str
    page_no: int
    county: str
    report_year: int | None
    report_month: int | None
    report_type: str
    image_count: int
    chart_score: int
    photo_score: int
    table_score: int
    risk_score: int
    asset_type: str
    text_excerpt: str
    slope_codes: str
    monitor_points: str


@dataclass
class ReportAssetIndex:
    asset_id: str
    file_hash: str
    file_name: str
    page_no: int | None
    asset_index: int
    asset_type: str
    inferred_label: str
    image_count_on_page: int
    text_excerpt: str
    slope_codes: str
    monitor_points: str


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compact_text(value: str) -> str:
    value = value.replace("\x00", "")
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def text_score(text_value: str, words: list[str]) -> int:
    compact = re.sub(r"\s+", "", text_value)
    return sum(compact.count(word) for word in words)


def infer_asset_type(chart_score: int, photo_score: int, table_score: int, image_count: int) -> str:
    if chart_score >= max(1, photo_score) and chart_score >= table_score:
        return "监测曲线/折线图"
    if photo_score > 0 and image_count > 0:
        return "现场照片/图片"
    if table_score > 0:
        return "表格/统计"
    if image_count > 0:
        return "图片"
    return "文本"


def infer_county(path: Path, text_value: str) -> str:
    source = path.name + "\n" + text_value[:3000]
    for county in COUNTIES:
        if county in source:
            return county
    return ""


def infer_period(path: Path, text_value: str) -> tuple[int | None, int | None]:
    sources = [path.name, text_value[:1500]]
    patterns = [
        r"[（(](\d{2})年([01]?\d)月",
        r"(20\d{2})[.\-年\s]*([01]?\d)月?",
        r"(20\d{2})([01]\d)",
    ]
    for source in sources:
        for pattern in patterns:
            for match in re.finditer(pattern, source):
                year = int(match.group(1))
                if year < 100:
                    year += 2000
                month = int(match.group(2))
                if 1 <= month <= 12:
                    return year, month
    return None, None


def infer_report_type(path: Path) -> str:
    name = path.name
    if "年报" in name or "成果报告" in name:
        return "年报"
    if "安全评估" in name:
        return "安全评估"
    if "调查报告" in name:
        return "调查报告"
    if "群测群防" in name:
        return "群测群防月报"
    if "专业监测" in name:
        return "专业监测月报"
    if "简报" in name:
        return "简报"
    if "月报" in name:
        return "工作月报"
    return "报告"


def infer_title(path: Path, text_value: str) -> str:
    for line in text_value.splitlines()[:60]:
        line = line.strip()
        if len(line) >= 8 and any(word in line for word in ("高切坡", "监测", "报告", "月报", "简报")):
            return line[:300]
    return path.stem[:300]


def slope_codes(text_value: str, limit: int = 20) -> list[str]:
    matches = re.findall(r"\b(?:[A-Z]{1,5}\d{3,6}|420\d{10,})\b", text_value)
    return unique_limited(matches, limit)


def monitor_points(text_value: str, limit: int = 20) -> list[str]:
    patterns = [
        r"\b[A-Z]{1,4}\d{3,5}-?[A-Z]?\d{0,3}\b",
        r"监测点[:：]?\s*([A-Za-z0-9\-]+)",
        r"测点[:：]?\s*([A-Za-z0-9\-]+)",
    ]
    values: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text_value):
            values.append(match if isinstance(match, str) else match[0])
    return unique_limited(values, limit)


def unique_limited(values: list[str], limit: int) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def docx_units(path: Path) -> tuple[list[dict], int, int, str]:
    ns = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    units: list[dict] = []
    media_count = 0
    table_count = 0
    full_text: list[str] = []
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        media_count = sum(1 for name in names if name.startswith("word/media/"))
        if "word/document.xml" not in names:
            return [], media_count, 0, ""
        root = ET.fromstring(zf.read("word/document.xml"))
        table_count = len(root.findall(".//w:tbl", ns))
        block_index = 0
        for child in list(root.find("w:body", ns) or []):
            if child.tag.endswith("}p"):
                line = "".join(t.text or "" for t in child.findall(".//w:t", ns)).strip()
                image_refs = [node.attrib.get(f"{{{ns['r']}}}embed", "") for node in child.findall(".//a:blip", ns)]
                if line or image_refs:
                    units.append({"index": block_index, "text": line, "images": len([x for x in image_refs if x])})
                    if line:
                        full_text.append(line)
                    block_index += 1
            elif child.tag.endswith("}tbl"):
                cell_text = "".join(t.text or "" for t in child.findall(".//w:t", ns)).strip()
                units.append({"index": block_index, "text": cell_text[:1200], "images": 0, "is_table": True})
                if cell_text:
                    full_text.append(cell_text)
                block_index += 1
    return units, media_count, table_count, "\n".join(full_text)


def analyze_docx(path: Path, file_hash: str) -> tuple[ReportDocIndex, list[ReportPageIndex], list[ReportAssetIndex]]:
    units, media_count, table_count, text_value = docx_units(path)
    county = infer_county(path, text_value)
    year, month = infer_period(path, text_value)
    report_type = infer_report_type(path)
    pages: list[ReportPageIndex] = []
    assets: list[ReportAssetIndex] = []
    page_no = 1
    group: list[dict] = []
    for unit in units:
        group.append(unit)
        if len(group) >= 18:
            pages.append(build_page(path, file_hash, page_no, county, year, month, report_type, group))
            group = []
            page_no += 1
    if group:
        pages.append(build_page(path, file_hash, page_no, county, year, month, report_type, group))

    asset_index = 0
    for page in pages:
        if page.image_count <= 0 and page.asset_type == "文本":
            continue
        for _ in range(max(1, page.image_count)):
            asset_index += 1
            assets.append(build_asset(path, file_hash, page, asset_index))

    doc = build_doc(path, file_hash, county, year, month, report_type, text_value, None, media_count, table_count, pages, "ok", "")
    return doc, pages, assets


def build_page(
    path: Path,
    file_hash: str,
    page_no: int,
    county: str,
    year: int | None,
    month: int | None,
    report_type: str,
    units: list[dict],
) -> ReportPageIndex:
    text_value = compact_text("\n".join(unit.get("text", "") for unit in units if unit.get("text")))
    image_count = sum(int(unit.get("images") or 0) for unit in units)
    table_score = text_score(text_value, TABLE_WORDS) + sum(1 for unit in units if unit.get("is_table"))
    chart_score = text_score(text_value, CHART_WORDS)
    photo_score = text_score(text_value, PHOTO_WORDS)
    risk_score = text_score(text_value, RISK_WORDS)
    asset_type = infer_asset_type(chart_score, photo_score, table_score, image_count)
    return ReportPageIndex(
        page_id=f"{file_hash[:16]}-{page_no:04d}",
        file_hash=file_hash,
        file_name=path.name,
        page_no=page_no,
        county=county,
        report_year=year,
        report_month=month,
        report_type=report_type,
        image_count=image_count,
        chart_score=chart_score,
        photo_score=photo_score,
        table_score=table_score,
        risk_score=risk_score,
        asset_type=asset_type,
        text_excerpt=text_value[:1200],
        slope_codes=json.dumps(slope_codes(text_value), ensure_ascii=False),
        monitor_points=json.dumps(monitor_points(text_value), ensure_ascii=False),
    )


def analyze_pdf(path: Path, file_hash: str) -> tuple[ReportDocIndex, list[ReportPageIndex], list[ReportAssetIndex]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    page_indexes: list[ReportPageIndex] = []
    assets: list[ReportAssetIndex] = []
    all_text: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text_value = compact_text(page.extract_text() or "")
        all_text.append(text_value)
        try:
            image_count = len(page.images)
        except Exception:
            image_count = 0
        chart_score = text_score(text_value, CHART_WORDS)
        photo_score = text_score(text_value, PHOTO_WORDS)
        table_score = text_score(text_value, TABLE_WORDS)
        risk_score = text_score(text_value, RISK_WORDS)
        page_index = ReportPageIndex(
            page_id=f"{file_hash[:16]}-{index:04d}",
            file_hash=file_hash,
            file_name=path.name,
            page_no=index,
            county="",
            report_year=None,
            report_month=None,
            report_type=infer_report_type(path),
            image_count=image_count,
            chart_score=chart_score,
            photo_score=photo_score,
            table_score=table_score,
            risk_score=risk_score,
            asset_type=infer_asset_type(chart_score, photo_score, table_score, image_count),
            text_excerpt=text_value[:1200],
            slope_codes=json.dumps(slope_codes(text_value), ensure_ascii=False),
            monitor_points=json.dumps(monitor_points(text_value), ensure_ascii=False),
        )
        page_indexes.append(page_index)
        if image_count or page_index.asset_type != "文本":
            for image_index in range(max(1, image_count)):
                assets.append(build_asset(path, file_hash, page_index, len(assets) + 1, image_index=image_index + 1))

    text_value = "\n".join(all_text)
    county = infer_county(path, text_value)
    year, month = infer_period(path, text_value)
    report_type = infer_report_type(path)
    for page in page_indexes:
        page.county = county
        page.report_year = year
        page.report_month = month
        page.report_type = report_type
    doc = build_doc(
        path,
        file_hash,
        county,
        year,
        month,
        report_type,
        text_value,
        len(reader.pages),
        sum(page.image_count for page in page_indexes),
        0,
        page_indexes,
        "ok",
        "",
    )
    return doc, page_indexes, assets


def build_asset(
    path: Path,
    file_hash: str,
    page: ReportPageIndex,
    asset_index: int,
    image_index: int | None = None,
) -> ReportAssetIndex:
    label = page.asset_type
    if page.asset_type == "监测曲线/折线图":
        label = "疑似监测点位移/降雨/水位曲线图"
    elif page.asset_type == "现场照片/图片":
        label = "疑似现场照片或巡查图片"
    elif page.asset_type == "表格/统计":
        label = "疑似监测成果或统计表"
    return ReportAssetIndex(
        asset_id=f"{file_hash[:16]}-{page.page_no:04d}-{asset_index:05d}",
        file_hash=file_hash,
        file_name=path.name,
        page_no=page.page_no,
        asset_index=image_index or asset_index,
        asset_type=page.asset_type,
        inferred_label=label,
        image_count_on_page=page.image_count,
        text_excerpt=page.text_excerpt[:1200],
        slope_codes=page.slope_codes,
        monitor_points=page.monitor_points,
    )


def build_doc(
    path: Path,
    file_hash: str,
    county: str,
    year: int | None,
    month: int | None,
    report_type: str,
    text_value: str,
    page_count: int | None,
    image_count: int,
    table_count: int,
    pages: list[ReportPageIndex],
    status: str,
    message: str,
) -> ReportDocIndex:
    return ReportDocIndex(
        file_hash=file_hash,
        file_name=path.name,
        file_path=str(path),
        file_ext=path.suffix.lower(),
        file_size=path.stat().st_size,
        county=county,
        report_year=year,
        report_month=month,
        report_type=report_type,
        title=infer_title(path, text_value),
        text_length=len(re.sub(r"\s+", "", text_value)),
        page_count=page_count,
        image_count=image_count,
        table_count=table_count,
        chart_page_count=sum(1 for page in pages if page.asset_type == "监测曲线/折线图"),
        photo_page_count=sum(1 for page in pages if page.asset_type == "现场照片/图片"),
        table_page_count=sum(1 for page in pages if page.asset_type == "表格/统计"),
        parse_status=status,
        parse_message=message,
        analyzed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def infer_title(path: Path, text_value: str) -> str:
    for line in text_value.splitlines()[:80]:
        line = line.strip()
        if len(line) >= 8 and any(word in line for word in ("高切坡", "监测", "报告", "月报", "简报")):
            return line[:300]
    return path.stem[:300]


def report_files(doc_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(doc_dir.rglob("*"))
        if path.is_file()
        and not path.name.startswith("~$")
        and path.suffix.lower() in {".docx", ".pdf"}
    ]


def analyze_file(path: Path) -> tuple[ReportDocIndex, list[ReportPageIndex], list[ReportAssetIndex]]:
    file_hash = file_sha256(path)
    try:
        if path.suffix.lower() == ".docx":
            return analyze_docx(path, file_hash)
        if path.suffix.lower() == ".pdf":
            return analyze_pdf(path, file_hash)
        raise ValueError(f"unsupported file type: {path.suffix}")
    except Exception as exc:
        doc = build_doc(
            path,
            file_hash,
            infer_county(path, ""),
            *infer_period(path, ""),
            infer_report_type(path),
            "",
            None,
            0,
            0,
            [],
            "parse_failed",
            str(exc),
        )
        return doc, [], []


def dedupe_docs(
    docs: list[ReportDocIndex],
    pages: list[ReportPageIndex],
    assets: list[ReportAssetIndex],
) -> tuple[list[ReportDocIndex], list[ReportPageIndex], list[ReportAssetIndex]]:
    seen = set()
    keep_hashes = set()
    deduped_docs = []
    for doc in docs:
        if doc.file_hash in seen:
            continue
        seen.add(doc.file_hash)
        keep_hashes.add(doc.file_hash)
        deduped_docs.append(doc)
    return (
        deduped_docs,
        [page for page in pages if page.file_hash in keep_hashes],
        [asset for asset in assets if asset.file_hash in keep_hashes],
    )


def write_outputs(out_dir: Path, docs: list[ReportDocIndex], pages: list[ReportPageIndex], assets: list[ReportAssetIndex]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "docs": len(docs),
        "pages": len(pages),
        "assets": len(assets),
        "images": sum(doc.image_count for doc in docs),
        "chart_pages": sum(doc.chart_page_count for doc in docs),
        "photo_pages": sum(doc.photo_page_count for doc in docs),
        "table_pages": sum(doc.table_page_count for doc in docs),
        "by_county": {},
    }
    pages_by_hash: dict[str, int] = {}
    for page in pages:
        pages_by_hash[page.file_hash] = pages_by_hash.get(page.file_hash, 0) + 1
    for doc in docs:
        county = doc.county or "未识别"
        summary["by_county"].setdefault(county, {"docs": 0, "pages": 0, "assets": 0, "chart_pages": 0})
        summary["by_county"][county]["docs"] += 1
        summary["by_county"][county]["pages"] += doc.page_count or pages_by_hash.get(doc.file_hash, 0)
        summary["by_county"][county]["assets"] += doc.image_count
        summary["by_county"][county]["chart_pages"] += doc.chart_page_count
    (out_dir / "report_doc_index.json").write_text(json.dumps([asdict(doc) for doc in docs], ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report_page_index.jsonl").write_text("\n".join(json.dumps(asdict(page), ensure_ascii=False) for page in pages), encoding="utf-8")
    (out_dir / "report_asset_index.jsonl").write_text("\n".join(json.dumps(asdict(asset), ensure_ascii=False) for asset in assets), encoding="utf-8")
    (out_dir / "report_asset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc-dir", default=str(DOC_DIR))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--sample-per-county", type=int, default=0)
    args = parser.parse_args()
    docs: list[ReportDocIndex] = []
    pages: list[ReportPageIndex] = []
    assets: list[ReportAssetIndex] = []
    paths = report_files(Path(args.doc_dir))
    if args.sample_per_county:
        paths = select_sample_files(paths, args.sample_per_county)
    for path in paths:
        doc, file_pages, file_assets = analyze_file(path)
        docs.append(doc)
        pages.extend(file_pages)
        assets.extend(file_assets)
        print(
            f"{doc.county or '-':4s} {doc.report_year or '-'}-{doc.report_month or '-'} "
            f"{doc.file_ext:5s} pages={doc.page_count or len(file_pages):4d} "
            f"images={doc.image_count:4d} charts={doc.chart_page_count:3d} {doc.file_name}"
        )
    docs, pages, assets = dedupe_docs(docs, pages, assets)
    write_outputs(Path(args.out_dir), docs, pages, assets)
    return 0


def select_sample_files(paths: list[Path], per_county: int) -> list[Path]:
    selected: list[Path] = []
    by_county = {county: [] for county in COUNTIES}
    for path in paths:
        name = path.name
        for county in COUNTIES:
            if county in name:
                by_county[county].append(path)
                break
    for county in COUNTIES:
        files = by_county[county]
        preferred = sorted(
            files,
            key=lambda item: (
                0 if "2025" in item.name else 1,
                0 if item.suffix.lower() == ".pdf" else 1,
                item.name,
            ),
        )
        county_selected: list[Path] = []
        seen_periods = set()
        seen_hashes = set()
        for item in preferred:
            try:
                item_hash = file_sha256(item)
            except Exception:
                item_hash = item.name
            if item_hash in seen_hashes:
                continue
            period = infer_period(item, "")
            if period in seen_periods and any(value is not None for value in period):
                continue
            county_selected.append(item)
            seen_hashes.add(item_hash)
            seen_periods.add(period)
            if len(county_selected) >= per_county:
                break
        if len(county_selected) < per_county:
            for item in preferred:
                if item in county_selected:
                    continue
                county_selected.append(item)
                if len(county_selected) >= per_county:
                    break
        selected.extend(county_selected)
    return selected


if __name__ == "__main__":
    raise SystemExit(main())
