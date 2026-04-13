import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DOCX = ROOT_DIR / "高切坡数据库设计文档.docx"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "backend" / "schema_exports"
TABLE_NAME_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]+)\s*$")


def normalize_name(value: str) -> str:
    return value.strip().strip('"').lower()


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\n", " ").split())


def load_dm_config() -> dict[str, str]:
    load_dotenv(ROOT_DIR / "backend" / ".env")
    import os

    config = {
        "user": os.getenv("DM_USER", ""),
        "password": os.getenv("DM_PASSWORD", ""),
        "host": os.getenv("DM_HOST", ""),
        "port": os.getenv("DM_PORT", ""),
    }
    missing = [key for key, value in config.items() if not value]
    if missing:
        raise RuntimeError(f"缺少达梦数据库配置: {', '.join(missing)}")
    return config


def build_dm_uri(config: dict[str, str]) -> str:
    password = quote_plus(config["password"])
    return f"dm+dmPython://{config['user']}:{password}@{config['host']}:{config['port']}/"


def serialize_default(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def export_database_schema() -> dict[str, Any]:
    config = load_dm_config()
    engine = create_engine(build_dm_uri(config))
    try:
        inspector = inspect(engine)
        table_names = sorted(inspector.get_table_names(), key=str.lower)
        tables = []
        for table_name in table_names:
            columns = inspector.get_columns(table_name)
            pk = inspector.get_pk_constraint(table_name) or {}
            primary_keys = set(pk.get("constrained_columns") or [])
            tables.append(
                {
                    "table_name": table_name,
                    "normalized_table_name": normalize_name(table_name),
                    "columns": [
                        {
                            "name": column.get("name", ""),
                            "normalized_name": normalize_name(column.get("name", "")),
                            "type": str(column.get("type", "")),
                            "nullable": bool(column.get("nullable", False)),
                            "default": serialize_default(column.get("default")),
                            "primary_key": column.get("name") in primary_keys,
                            "comment": clean_text(column.get("comment")),
                        }
                        for column in columns
                    ],
                }
            )

        return {
            "source": "database",
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "table_count": len(tables),
            "tables": tables,
        }
    finally:
        engine.dispose()


def iter_doc_blocks(doc: Document):
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def parse_doc_table(table: Table) -> list[dict[str, str]]:
    if not table.rows:
        return []

    fields = []
    for row in table.rows[1:]:
        cells = [clean_text(cell.text) for cell in row.cells]
        if not cells or not cells[0]:
            continue
        fields.append(
            {
                "name": cells[0],
                "normalized_name": normalize_name(cells[0]),
                "type": cells[1] if len(cells) > 1 else "",
                "primary_key_mark": cells[2] if len(cells) > 2 else "",
                "nullable_mark": cells[3] if len(cells) > 3 else "",
                "default": cells[4] if len(cells) > 4 else "",
                "comment": cells[5] if len(cells) > 5 else "",
            }
        )
    return fields


def extract_doc_schema(docx_path: Path) -> dict[str, Any]:
    doc = Document(docx_path)
    recent_paragraphs: list[str] = []
    tables = []
    unnamed_count = 0

    for block in iter_doc_blocks(doc):
        if isinstance(block, Paragraph):
            text = clean_text(block.text)
            if text:
                recent_paragraphs.append(text)
                recent_paragraphs = recent_paragraphs[-6:]
            continue

        table_title = ""
        table_name = ""
        section = ""

        previous_paragraph = recent_paragraphs[-1] if recent_paragraphs else ""
        match = TABLE_NAME_RE.search(previous_paragraph)
        if match:
            table_title = previous_paragraph
            table_name = match.group(1)
            if len(recent_paragraphs) > 1:
                section = recent_paragraphs[-2]
        else:
            unnamed_count += 1
            table_name = f"unnamed_doc_table_{unnamed_count}"
            table_title = previous_paragraph or table_name
            section = recent_paragraphs[-2] if len(recent_paragraphs) > 1 else ""

        fields = parse_doc_table(block)
        tables.append(
            {
                "table_name": table_name,
                "normalized_table_name": normalize_name(table_name),
                "table_title": table_title,
                "section": section,
                "columns": fields,
            }
        )

    return {
        "source": str(docx_path),
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "table_count": len(tables),
        "tables": tables,
    }


def comparable_type(value: str) -> str:
    value = value.lower()
    value = value.replace("varchar2", "varchar")
    value = value.replace("integer", "int")
    value = value.replace("numeric", "number")
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"char\)", ")", value)
    return value


def compare_schemas(db_schema: dict[str, Any], doc_schema: dict[str, Any]) -> dict[str, Any]:
    db_tables = {table["normalized_table_name"]: table for table in db_schema["tables"]}
    doc_tables = {
        table["normalized_table_name"]: table
        for table in doc_schema["tables"]
        if not table["table_name"].startswith("unnamed_doc_table_")
    }

    common_table_keys = sorted(set(db_tables) & set(doc_tables))
    doc_only_keys = sorted(set(doc_tables) - set(db_tables))
    db_only_keys = sorted(set(db_tables) - set(doc_tables))

    table_results = []
    for key in common_table_keys:
        db_table = db_tables[key]
        doc_table = doc_tables[key]
        db_columns = {column["normalized_name"]: column for column in db_table["columns"]}
        doc_columns = {column["normalized_name"]: column for column in doc_table["columns"]}
        common_columns = sorted(set(db_columns) & set(doc_columns))

        type_mismatches = []
        for column_key in common_columns:
            db_column = db_columns[column_key]
            doc_column = doc_columns[column_key]
            db_type = comparable_type(db_column["type"])
            doc_type = comparable_type(doc_column["type"])
            if doc_type and db_type and doc_type not in db_type and db_type not in doc_type:
                type_mismatches.append(
                    {
                        "column": db_column["name"],
                        "database_type": db_column["type"],
                        "document_type": doc_column["type"],
                    }
                )

        table_results.append(
            {
                "table_name": db_table["table_name"],
                "document_title": doc_table["table_title"],
                "database_column_count": len(db_table["columns"]),
                "document_column_count": len(doc_table["columns"]),
                "missing_in_database_columns": [
                    doc_columns[column_key]["name"]
                    for column_key in sorted(set(doc_columns) - set(db_columns))
                ],
                "extra_in_database_columns": [
                    db_columns[column_key]["name"]
                    for column_key in sorted(set(db_columns) - set(doc_columns))
                ],
                "type_mismatches": type_mismatches,
            }
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "database_table_count": db_schema["table_count"],
            "document_table_count": doc_schema["table_count"],
            "matched_table_count": len(common_table_keys),
            "document_only_table_count": len(doc_only_keys),
            "database_only_table_count": len(db_only_keys),
            "tables_with_column_differences": sum(
                1
                for table in table_results
                if table["missing_in_database_columns"]
                or table["extra_in_database_columns"]
                or table["type_mismatches"]
            ),
        },
        "document_only_tables": [doc_tables[key]["table_name"] for key in doc_only_keys],
        "database_only_tables": [db_tables[key]["table_name"] for key in db_only_keys],
        "matched_tables": table_results,
        "unnamed_document_tables": [
            table
            for table in doc_schema["tables"]
            if table["table_name"].startswith("unnamed_doc_table_")
        ],
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export and compare DM database schema with Word schema.")
    parser.add_argument("--docx", type=Path, default=DEFAULT_DOCX)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    db_schema = export_database_schema()
    doc_schema = extract_doc_schema(args.docx)
    comparison = compare_schemas(db_schema, doc_schema)

    write_json(args.out_dir / "database_schema.json", db_schema)
    write_json(args.out_dir / "document_schema.json", doc_schema)
    write_json(args.out_dir / "schema_comparison.json", comparison)

    print(json.dumps(comparison["summary"], ensure_ascii=False, indent=2))
    print(f"输出目录: {args.out_dir}")


if __name__ == "__main__":
    main()
