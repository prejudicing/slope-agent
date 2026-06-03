"""导出 database_schema_explained.json 中枚举字段的人工校验清单。

重点输出带 0/1 语义的字段，方便人工检查：
- 哪些字段 1 代表肯定/启用/正常
- 哪些字段 1 代表否定/未删除/未停止
- 哪些字段虽然包含 0/1，但语义并不对称

同时直接查询真实数据库，为每个字段补充：
- 总记录数
- 值为 0 的记录数
- 值为 1 的记录数
- 空值记录数
- 其他值记录数
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import build_db_uri

SCHEMA_PATH = ROOT_DIR / "backend" / "schema_exports" / "database_schema_explained.json"
CSV_OUTPUT = ROOT_DIR / "backend" / "schema_exports" / "enum_fields_01_review.csv"
MD_OUTPUT = ROOT_DIR / "docs" / "notes" / "枚举字段01人工校验清单.md"


def format_hints(value_hints: dict) -> str:
    if not value_hints:
        return ""
    return "；".join(f"{key}={value}" for key, value in value_hints.items())


def guess_polarity(value: str) -> str:
    """给人工校验做一个粗分类，最终仍以人工判断为准。"""
    text = (value or "").strip()
    positive_words = ("正常", "启用", "有", "存在", "已", "完整", "是", "应急", "异常")
    negative_words = ("未", "无", "停用", "删除", "停止", "非")

    if any(word in text for word in negative_words):
        return "1偏否定/反向"
    if any(word in text for word in positive_words):
        return "1偏肯定/正向"
    return "需人工判断"


def fetch_value_counts(table_name: str, field_name: str) -> dict[str, int]:
    """直接通过 SQL 统计字段中 0/1/空值/其他值 的记录数。"""
    uri = build_db_uri()
    engine = create_engine(uri)
    try:
        sql = text(
            f"""
            SELECT
              COUNT(*) AS total_count,
              SUM(CASE WHEN "{field_name}" IS NULL THEN 1 ELSE 0 END) AS null_count,
              SUM(CASE WHEN TRIM(CAST("{field_name}" AS VARCHAR(64))) = '0' THEN 1 ELSE 0 END) AS zero_count,
              SUM(CASE WHEN TRIM(CAST("{field_name}" AS VARCHAR(64))) = '1' THEN 1 ELSE 0 END) AS one_count
            FROM "{table_name}"
            """
        )
        with engine.connect() as conn:
            row = conn.execute(sql).mappings().first()
    finally:
        engine.dispose()

    normalized_row = {str(key).lower(): value for key, value in dict(row).items()}
    total_count = int(normalized_row.get("total_count") or 0)
    null_count = int(normalized_row.get("null_count") or 0)
    zero_count = int(normalized_row.get("zero_count") or 0)
    one_count = int(normalized_row.get("one_count") or 0)
    other_count = total_count - null_count - zero_count - one_count
    return {
        "total_count": total_count,
        "zero_count": zero_count,
        "one_count": one_count,
        "null_count": null_count,
        "other_count": max(other_count, 0),
    }


def load_rows() -> list[dict]:
    data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for table in data.get("tables", []):
        for field in table.get("fields", []):
            value_hints = field.get("value_hints") or {}
            if "0" not in value_hints and "1" not in value_hints:
                continue

            counts = fetch_value_counts(table.get("table_name", ""), field.get("name", ""))

            rows.append(
                {
                    "table_name": table.get("table_name", ""),
                    "business_domain": table.get("business_domain", ""),
                    "field_name": field.get("name", ""),
                    "field_type": field.get("type", ""),
                    "business_meaning": field.get("business_meaning", ""),
                    "comment": field.get("comment", "") or "",
                    "comment_source": field.get("comment_source", "") or "",
                    "value_hints": format_hints(value_hints),
                    "zero_meaning": value_hints.get("0", ""),
                    "one_meaning": value_hints.get("1", ""),
                    "one_polarity_guess": guess_polarity(value_hints.get("1", "")),
                    "total_count": counts["total_count"],
                    "zero_count": counts["zero_count"],
                    "one_count": counts["one_count"],
                    "null_count": counts["null_count"],
                    "other_count": counts["other_count"],
                }
            )
    rows.sort(key=lambda item: (item["table_name"], item["field_name"]))
    return rows


def write_csv(rows: list[dict]) -> None:
    CSV_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with CSV_OUTPUT.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "table_name",
                "business_domain",
                "field_name",
                "field_type",
                "business_meaning",
                "comment",
                "comment_source",
                "value_hints",
                "zero_meaning",
                "one_meaning",
                "one_polarity_guess",
                "total_count",
                "zero_count",
                "one_count",
                "null_count",
                "other_count",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict]) -> None:
    MD_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 枚举字段01人工校验清单",
        "",
        "来源：`backend/schema_exports/database_schema_explained.json`",
        "",
        "说明：这里只导出 `value_hints` 中包含 `0` 或 `1` 的字段，方便人工核对 `0/1` 语义是否一致。",
        "",
        "新增统计列说明：",
        "",
        "- `总记录数`：该表该字段所在表的总记录数",
        "- `0记录数`：字段值等于 `0` 的记录数",
        "- `1记录数`：字段值等于 `1` 的记录数",
        "- `空值记录数`：字段值为 `NULL` 的记录数",
        "- `其他值记录数`：除了 `0 / 1 / NULL` 之外的记录数",
        "",
        "当维护人员对字段口径记不清时，可以优先结合 `0/1` 计数判断哪个值更像常态，再回看字段注释和业务含义。",
        "",
        f"共导出 **{len(rows)}** 个字段。",
        "",
        "| 表名 | 业务域 | 字段 | 含义 | 0 的含义 | 1 的含义 | 总记录数 | 0记录数 | 1记录数 | 空值记录数 | 其他值记录数 | 1 的自动判断 | 备注/注释 |",
        "|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|",
    ]

    for row in rows:
        lines.append(
            "| {table_name} | {business_domain} | {field_name} | {business_meaning} | {zero_meaning} | {one_meaning} | {total_count} | {zero_count} | {one_count} | {null_count} | {other_count} | {one_polarity_guess} | {comment} |".format(
                **{key: str(value).replace("|", "/") for key, value in row.items()}
            )
        )

    MD_OUTPUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    rows = load_rows()
    write_csv(rows)
    write_markdown(rows)
    print(f"导出完成：{CSV_OUTPUT}")
    print(f"导出完成：{MD_OUTPUT}")
    print(f"字段数量：{len(rows)}")


if __name__ == "__main__":
    main()
