"""高频业务问题的确定性查询模板。

这类问题不交给 LLM 自由生成 SQL，避免同一句话在关键业务口径上漂移。
"""

from typing import Any


ABNORMAL_TYPE_FIELDS = [
    ("isCrack", "裂缝"),
    ("isRead", "坡面裂痕"),
    ("sfyls", "落石"),
    ("slopeFailure", "坡面异常破坏"),
    ("sfypmph", "坡面破坏"),
    ("wallCracking", "道路或挡墙开裂"),
    ("sfydtqkl", "挡土墙开裂"),
    ("facilities", "监测设施异常"),
    ("disorderlyPush", "坡周乱搭乱堆"),
    ("sfypsgds", "排水沟堵塞"),
    ("sfypskds", "排水口堵塞"),
    ("pmsfygzfq", "坡面鼓胀或反翘"),
]


def get_deterministic_query(question: str) -> dict[str, Any] | None:
    """识别必须稳定回答的高频业务问题。"""
    if _is_abnormal_type_question(question):
        # 这类问题的风险在于：LLM 容易把 overallSituation=1 误说成某种具体异常。
        # 因此直接固定 SQL 和后处理逻辑，确保异常类型来自明确的异常字段。
        return {
            "name": "abnormal_type",
            "tables": ["tb_hcs_monitoring", "geo_gqp_jbxx"],
            "sql": _abnormal_type_sql(),
            "summary": "按群测群防监测记录中的具体异常项识别异常类型，未仅以“总体情况=异常”作为异常类型。",
        }
    if _is_county_abnormal_compare_question(question):
        # “各区县异常数量对比/分布”是典型汇报口径问题，应该固定成按区县聚合的稳定 SQL。
        # 这里按异常高切坡数量统计，避免把同一个高切坡的多条监测记录重复计数。
        return {
            "name": "county_abnormal_compare",
            "tables": ["tb_hcs_monitoring", "geo_gqp_jbxx"],
            "sql": _county_abnormal_compare_sql(),
            "summary": "按区县统计存在异常监测记录的高切坡数量，用于横向对比各区县异常高切坡分布。",
        }
    return None


def enrich_rows(query_name: str, columns: list[str], rows: list[dict]) -> tuple[list[str], list[dict]]:
    """为确定性查询补充业务解释字段。"""
    if query_name != "abnormal_type":
        return columns, rows
    return _enrich_abnormal_type_rows(columns, rows)


def _is_abnormal_type_question(question: str) -> bool:
    compact = "".join(question.split())
    return (
        "异常" in compact
        and (
            "异常类型" in compact
            or "哪一种异常" in compact
            or "哪类异常" in compact
            or "属于哪一种" in compact
            or "属于哪类" in compact
        )
    )


def _is_county_abnormal_compare_question(question: str) -> bool:
    compact = "".join(question.split())
    has_county_scope = "区县" in compact
    has_abnormal_target = "高切坡" in compact and "异常" in compact
    has_compare_intent = any(keyword in compact for keyword in ("对比", "比较", "分布", "排行", "排名"))
    has_count_intent = "数量" in compact or "多少" in compact
    return has_county_scope and has_abnormal_target and (has_compare_intent or has_count_intent)


def _abnormal_type_sql() -> str:
    abnormal_conditions = " OR ".join(
        f"m.{field_name} = 1" for field_name, _ in ABNORMAL_TYPE_FIELDS
    )
    return f"""
SELECT
  m.gqpbh,
  b.gqpmc,
  b.ssqx,
  m.isCrack,
  m.isRead,
  m.sfyls,
  m.slopeFailure,
  m.sfypmph,
  m.wallCracking,
  m.sfydtqkl,
  m.facilities,
  m.disorderlyPush,
  m.sfypsgds,
  m.sfypskds,
  m.pmsfygzfq,
  m.overallSituation,
  m.hcSlopeStatus,
  m.statusReason,
  m.createdOn
FROM tb_hcs_monitoring m
LEFT JOIN geo_gqp_jbxx b ON m.gqpbh = b.gqpbh
WHERE {abnormal_conditions}
ORDER BY m.createdOn DESC, m.gqpbh ASC
""".strip()


def _county_abnormal_compare_sql() -> str:
    abnormal_conditions = " OR ".join(
        f"m.{field_name} = 1" for field_name, _ in ABNORMAL_TYPE_FIELDS
    )
    return f"""
SELECT
  b.ssqx,
  COUNT(DISTINCT m.gqpbh) AS abnormal_slope_count
FROM tb_hcs_monitoring m
JOIN geo_gqp_jbxx b ON m.gqpbh = b.gqpbh
WHERE b.delete_flag = 1
  AND b.ssqx IS NOT NULL
  AND ({abnormal_conditions})
GROUP BY b.ssqx
ORDER BY abnormal_slope_count DESC, b.ssqx ASC
""".strip()


def _is_truthy_flag(value) -> bool:
    return str(value).strip() in {"1", "1.0", "true", "True"}


def _enrich_abnormal_type_rows(columns: list[str], rows: list[dict]) -> tuple[list[str], list[dict]]:
    flag_fields = {field_name for field_name, _ in ABNORMAL_TYPE_FIELDS}
    # 结果表里不直接暴露一串 0/1 标志位，而是折叠成一个更适合业务阅读的 abnormal_type 字段。
    display_columns = [
        column
        for column in columns
        if column not in flag_fields
    ]
    if "abnormal_type" not in display_columns:
        insert_at = 2 if len(display_columns) >= 2 else len(display_columns)
        display_columns.insert(insert_at, "abnormal_type")

    enriched_rows = []
    for row in rows:
        abnormal_types = [
            label
            for field_name, label in ABNORMAL_TYPE_FIELDS
            if _is_truthy_flag(row.get(field_name))
        ]
        enriched = {
            column: row.get(column, "")
            for column in display_columns
            if column != "abnormal_type"
        }
        enriched["abnormal_type"] = "、".join(abnormal_types) or "未识别到具体异常项"
        enriched_rows.append(enriched)

    return display_columns, enriched_rows
