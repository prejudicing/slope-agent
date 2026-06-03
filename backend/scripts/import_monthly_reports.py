from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus
from xml.etree import ElementTree

from sqlalchemy import create_engine, text


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
DEFAULT_DOC_DIR = PROJECT_DIR.parent / "doc"
DEFAULT_OUT_DIR = PROJECT_DIR / "backend" / "report_extract"
BUNDLED_PYTHON_PACKAGES = Path(
    r"C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\python"
)
BUNDLED_SITE_PACKAGES = BUNDLED_PYTHON_PACKAGES / "Lib" / "site-packages"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if BUNDLED_PYTHON_PACKAGES.exists() and str(BUNDLED_PYTHON_PACKAGES) not in sys.path:
    sys.path.append(str(BUNDLED_PYTHON_PACKAGES))
if BUNDLED_SITE_PACKAGES.exists() and str(BUNDLED_SITE_PACKAGES) not in sys.path:
    sys.path.append(str(BUNDLED_SITE_PACKAGES))

from app.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER  # noqa: E402


COUNTIES = ("巴东县", "兴山县", "夷陵区", "秭归县")
KEYWORDS = ("异常", "预警", "变形", "裂缝", "降雨", "稳定", "巡查", "监测", "处置", "风险", "告警")
QUESTION_TARGET = 80


@dataclass
class ReportDoc:
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
    parse_status: str
    parse_message: str
    key_points: str
    mentioned_slopes: str
    extracted_at: str


@dataclass
class ReportChunk:
    chunk_id: str
    file_hash: str
    chunk_index: int
    county: str
    report_year: int | None
    report_month: int | None
    report_type: str
    content: str


@dataclass
class ReportQuestion:
    question_id: str
    question: str
    expected_source: str
    county: str
    report_year: int | None
    report_month: int | None
    query_type: str
    test_status: str = "pending"
    test_result: str = ""


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_text(value: str) -> str:
    value = value.replace("\x00", "")
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def extract_docx_text(path: Path) -> str:
    parts: list[str] = []
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as zf:
        for name in ("word/document.xml", "word/header1.xml", "word/footer1.xml"):
            if name not in zf.namelist():
                continue
            root = ElementTree.fromstring(zf.read(name))
            paragraphs = []
            for paragraph in root.findall(".//w:p", ns):
                texts = [node.text or "" for node in paragraph.findall(".//w:t", ns)]
                line = "".join(texts).strip()
                if line:
                    paragraphs.append(line)
            parts.extend(paragraphs)
    return clean_text("\n".join(parts))


def extract_pdf_text(path: Path) -> tuple[str, int | None, str]:
    try:
        from pypdf import PdfReader
    except Exception as exc:
        return "", None, f"pypdf unavailable: {exc}"

    try:
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return clean_text("\n".join(pages)), len(reader.pages), ""
    except Exception as exc:
        return "", None, str(exc)


def infer_county(path: Path, text_value: str) -> str:
    source = path.name + "\n" + text_value[:4000]
    for county in COUNTIES:
        if county in source:
            return county
    return ""


def infer_period(path: Path, text_value: str) -> tuple[int | None, int | None]:
    name = path.name
    filename_patterns = [
        r"[（(](\d{2})年(1[0-2]|0?[1-9])月",
        r"(20\d{2})[.．年]\s*(1[0-2]|0?[1-9])月?",
        r"(20\d{2})(0[1-9]|1[0-2])(?!\d)",
    ]
    for pattern in filename_patterns:
        for match in re.finditer(pattern, name):
            year = int(match.group(1))
            if year < 100:
                year += 2000
            return year, int(match.group(2))

    annual_match = re.search(r"(20\d{2})年", name)
    if annual_match and ("年报" in name or "成果报告" in name):
        return int(annual_match.group(1)), None

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
    for line in text_value.splitlines()[:40]:
        line = line.strip()
        if len(line) >= 8 and any(word in line for word in ("高切坡", "监测", "报告", "月报", "简报")):
            return line[:300]
    return path.stem[:300]


def extract_key_points(text_value: str) -> str:
    candidates = []
    for piece in re.split(r"[。；;\n]", text_value):
        line = piece.strip()
        if 16 <= len(line) <= 220 and any(keyword in line for keyword in KEYWORDS):
            candidates.append(line)
    unique = []
    seen = set()
    for item in candidates:
        compact = re.sub(r"\s+", "", item)
        if compact in seen:
            continue
        seen.add(compact)
        unique.append(item)
        if len(unique) >= 12:
            break
    return json.dumps(unique, ensure_ascii=False)


def extract_slopes(text_value: str) -> str:
    matches = re.findall(r"\b(?:[A-Z]{1,5}\d{3,6}|420\d{10,})\b", text_value)
    unique = []
    seen = set()
    for item in matches:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
        if len(unique) >= 80:
            break
    return json.dumps(unique, ensure_ascii=False)


def split_chunks(doc: ReportDoc, text_value: str, max_chars: int = 1800) -> list[ReportChunk]:
    paragraphs = [p.strip() for p in re.split(r"\n{1,}", text_value) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 1 > max_chars and current:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return [
        ReportChunk(
            chunk_id=f"{doc.file_hash[:16]}-{index:04d}",
            file_hash=doc.file_hash,
            chunk_index=index,
            county=doc.county,
            report_year=doc.report_year,
            report_month=doc.report_month,
            report_type=doc.report_type,
            content=chunk,
        )
        for index, chunk in enumerate(chunks)
    ]


def parse_report(path: Path) -> tuple[ReportDoc, list[ReportChunk]]:
    file_hash = file_sha256(path)
    ext = path.suffix.lower()
    page_count = None
    message = ""
    try:
        if ext == ".docx":
            text_value = extract_docx_text(path)
        elif ext == ".pdf":
            text_value, page_count, message = extract_pdf_text(path)
        else:
            text_value = ""
            message = f"unsupported extension: {ext}"
    except Exception as exc:
        text_value = ""
        message = str(exc)

    county = infer_county(path, text_value)
    year, month = infer_period(path, text_value)
    status = "ok" if len(text_value) >= 200 else "needs_ocr" if ext == ".pdf" else "parse_failed"
    doc = ReportDoc(
        file_hash=file_hash,
        file_name=path.name,
        file_path=str(path),
        file_ext=ext,
        file_size=path.stat().st_size,
        county=county,
        report_year=year,
        report_month=month,
        report_type=infer_report_type(path),
        title=infer_title(path, text_value),
        text_length=len(text_value),
        page_count=page_count,
        parse_status=status,
        parse_message=message,
        key_points=extract_key_points(text_value),
        mentioned_slopes=extract_slopes(text_value),
        extracted_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    chunks = split_chunks(doc, text_value) if status == "ok" else []
    return doc, chunks


def iter_report_files(doc_dir: Path) -> Iterable[Path]:
    for path in sorted(doc_dir.rglob("*")):
        if path.is_file() and not path.name.startswith("~$") and path.suffix.lower() in {".docx", ".pdf"}:
            yield path


def make_questions(docs: list[ReportDoc]) -> list[ReportQuestion]:
    questions: list[ReportQuestion] = []
    for doc in docs:
        if doc.parse_status != "ok":
            continue
        period = f"{doc.report_year}年{doc.report_month}月" if doc.report_year and doc.report_month else ""
        prefix = "".join(part for part in (period, doc.county, doc.report_type) if part)
        candidates = [
            (f"{prefix}的主要监测结论是什么？", "summary"),
            (f"{prefix}中提到哪些异常、风险或预警情况？", "risk"),
            (f"{prefix}里有哪些高切坡编号或重点点位？", "slope_codes"),
        ]
        if doc.county:
            candidates.append((f"{doc.county}在{period or '该期报告'}的高切坡监测工作情况如何？", "county_month"))
        if doc.report_type in {"专业监测月报", "工作月报", "简报"}:
            candidates.append((f"{prefix}的变形监测和稳定性评价是什么？", "deformation"))
        for question, qtype in candidates:
            qid = hashlib.sha1((doc.file_hash + question).encode("utf-8")).hexdigest()[:24]
            questions.append(
                ReportQuestion(
                    question_id=qid,
                    question=question,
                    expected_source=doc.file_name,
                    county=doc.county,
                    report_year=doc.report_year,
                    report_month=doc.report_month,
                    query_type=qtype,
                )
            )
            if len(questions) >= QUESTION_TARGET:
                return questions
    return questions


def write_json_outputs(out_dir: Path, docs: list[ReportDoc], chunks: list[ReportChunk], questions: list[ReportQuestion]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "monthly_report_docs.json").write_text(
        json.dumps([asdict(item) for item in docs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "monthly_report_chunks.jsonl").write_text(
        "\n".join(json.dumps(asdict(item), ensure_ascii=False) for item in chunks),
        encoding="utf-8",
    )
    (out_dir / "monthly_report_questions.json").write_text(
        json.dumps([asdict(item) for item in questions], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def dm_engine():
    password = quote_plus(DM_PASSWORD)
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def clean_db_value(value):
    if value is None or isinstance(value, (int, float)):
        return value
    text_value = str(value).replace("\x00", "").strip()
    return text_value.encode("gbk", errors="replace").decode("gbk", errors="replace")


def clean_db_row(row: dict) -> dict:
    return {key: clean_db_value(value) for key, value in row.items()}


def create_tables(conn) -> None:
    conn.execute(text(
        """
        CREATE TABLE ai_monthly_report_doc (
          file_hash VARCHAR(64) PRIMARY KEY,
          file_name VARCHAR(500),
          file_path VARCHAR(1000),
          file_ext VARCHAR(20),
          file_size BIGINT,
          county VARCHAR(100),
          report_year INT,
          report_month INT,
          report_type VARCHAR(100),
          title VARCHAR(800),
          text_length INT,
          page_count INT,
          parse_status VARCHAR(50),
          parse_message VARCHAR(1000),
          key_points CLOB,
          mentioned_slopes CLOB,
          extracted_at VARCHAR(30)
        )
        """
    ))
    conn.execute(text(
        """
        CREATE TABLE ai_monthly_report_chunk (
          chunk_id VARCHAR(80) PRIMARY KEY,
          file_hash VARCHAR(64),
          chunk_index INT,
          county VARCHAR(100),
          report_year INT,
          report_month INT,
          report_type VARCHAR(100),
          content CLOB
        )
        """
    ))
    conn.execute(text(
        """
        CREATE TABLE ai_monthly_report_question (
          question_id VARCHAR(80) PRIMARY KEY,
          question VARCHAR(1000),
          expected_source VARCHAR(500),
          county VARCHAR(100),
          report_year INT,
          report_month INT,
          query_type VARCHAR(100),
          test_status VARCHAR(50),
          test_result CLOB
        )
        """
    ))


def ensure_tables(conn) -> None:
    existing = {
        row[0].lower()
        for row in conn.execute(text("SELECT table_name FROM user_tables")).fetchall()
    }
    if "ai_monthly_report_doc" not in existing:
        create_tables(conn)


def replace_rows(conn, docs: list[ReportDoc], chunks: list[ReportChunk], questions: list[ReportQuestion]) -> None:
    conn.execute(text("DELETE FROM ai_monthly_report_question"))
    conn.execute(text("DELETE FROM ai_monthly_report_chunk"))
    conn.execute(text("DELETE FROM ai_monthly_report_doc"))
    for doc in docs:
        conn.execute(text(
            """
            INSERT INTO ai_monthly_report_doc (
              file_hash, file_name, file_path, file_ext, file_size, county, report_year, report_month,
              report_type, title, text_length, page_count, parse_status, parse_message, key_points,
              mentioned_slopes, extracted_at
            ) VALUES (
              :file_hash, :file_name, :file_path, :file_ext, :file_size, :county, :report_year, :report_month,
              :report_type, :title, :text_length, :page_count, :parse_status, :parse_message, :key_points,
              :mentioned_slopes, :extracted_at
            )
        """
        ), clean_db_row(asdict(doc)))
    for chunk in chunks:
        conn.execute(text(
            """
            INSERT INTO ai_monthly_report_chunk (
              chunk_id, file_hash, chunk_index, county, report_year, report_month, report_type, content
            ) VALUES (
              :chunk_id, :file_hash, :chunk_index, :county, :report_year, :report_month, :report_type, :content
            )
            """
        ), clean_db_row(asdict(chunk)))
    for question in questions:
        conn.execute(text(
            """
            INSERT INTO ai_monthly_report_question (
              question_id, question, expected_source, county, report_year, report_month,
              query_type, test_status, test_result
            ) VALUES (
              :question_id, :question, :expected_source, :county, :report_year, :report_month,
              :query_type, :test_status, :test_result
            )
            """
        ), clean_db_row(asdict(question)))


def import_to_dm(docs: list[ReportDoc], chunks: list[ReportChunk], questions: list[ReportQuestion]) -> None:
    engine = dm_engine()
    try:
        with engine.begin() as conn:
            ensure_tables(conn)
            replace_rows(conn, docs, chunks, questions)
    finally:
        engine.dispose()


def dedupe_docs(docs: list[ReportDoc], chunks: list[ReportChunk]) -> tuple[list[ReportDoc], list[ReportChunk]]:
    seen = set()
    deduped_docs = []
    for doc in docs:
        if doc.file_hash in seen:
            continue
        seen.add(doc.file_hash)
        deduped_docs.append(doc)
    chunk_seen = set()
    deduped_chunks = []
    for chunk in chunks:
        if chunk.file_hash not in seen or chunk.chunk_id in chunk_seen:
            continue
        chunk_seen.add(chunk.chunk_id)
        deduped_chunks.append(chunk)
    return deduped_docs, deduped_chunks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc-dir", default=str(DEFAULT_DOC_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--import-db", action="store_true")
    args = parser.parse_args()

    docs: list[ReportDoc] = []
    chunks: list[ReportChunk] = []
    for path in iter_report_files(Path(args.doc_dir)):
        doc, doc_chunks = parse_report(path)
        docs.append(doc)
        chunks.extend(doc_chunks)
        print(f"{doc.parse_status:9s} {doc.text_length:7d} {path.name}")

    docs, chunks = dedupe_docs(docs, chunks)
    questions = make_questions(docs)
    write_json_outputs(Path(args.out_dir), docs, chunks, questions)
    if args.import_db:
        import_to_dm(docs, chunks, questions)

    ok_count = sum(1 for item in docs if item.parse_status == "ok")
    needs_ocr = sum(1 for item in docs if item.parse_status == "needs_ocr")
    print(json.dumps({
        "docs": len(docs),
        "ok": ok_count,
        "needs_ocr": needs_ocr,
        "chunks": len(chunks),
        "questions": len(questions),
        "out_dir": str(Path(args.out_dir)),
        "import_db": args.import_db,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
