"""对真实业务表做数据画像，并生成 Agent 初始业务知识包。"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import build_db_uri, get_db_provider

SCHEMA_DIR = ROOT_DIR / "backend" / "schema_exports"
DEFAULT_SCHEMA = SCHEMA_DIR / "database_schema_explained.json"
DEFAULT_PROFILE = SCHEMA_DIR / "table_profile.json"
DEFAULT_CORE = SCHEMA_DIR / "core_table_candidates.json"
DEFAULT_STARTER = SCHEMA_DIR / "business_starter_pack.json"

SYSTEM_TABLES = {"t_user", "t_user_role", "t_role", "t_role_menu", "t_menus"}
HIGH_VALUE_TABLES = {
    "geo_gqp_jbxx",
    "tb_hcs_monitoring",
    "geo_dzbjjbxx",
    "geo_gqp_zyjc",
    "t_warning_report_content",
    "t_review_record",
    "t_warning_report",
    "t_danger_report",
    "t_monthly",
    "tb_hcs_personnel",
}
ENUM_NAME_HINTS = (
    "status",
    "state",
    "flag",
    "type",
    "level",
    "sf",
    "is",
    "aqdj",
    "gqpzt",
    "warning",
    "delete",
)
TIME_EXACT_NAMES = {
    "createdon",
    "updatedon",
    "autidedon",
    "review_time",
    "create_time",
    "update_time",
    "tb_time",
    "last_warning_date",
    "occurrence_time",
    "photoon",
    "tbsj",
    "scyjsj",
    "sjtbsj",
    "kgrq",
    "wgrq",
    "jgrq",
    "jgysrq",
    "gjysrq",
}


def normalize(value: str) -> str:
    """统一字段名/表名格式，便于规则判断。"""
    return value.strip().strip('"').lower()


def quote_identifier(name: str) -> str:
    """保留原大小写，用双引号避免大小写或关键字问题。"""
    return '"' + name.replace('"', '""') + '"'


def load_db_env() -> None:
    """从 backend/.env 加载数据库连接配置。"""
    load_dotenv(ROOT_DIR / "backend" / ".env")


def example_limit_sql(select_clause: str, body_clause: str, limit: int = 20) -> str:
    """按当前数据库方言生成带样本限制的示例 SQL。"""
    if get_db_provider() == "sqlserver":
        return f"SELECT TOP {limit} {select_clause} {body_clause}"
    return f"SELECT {select_clause} {body_clause} LIMIT {limit}"


def is_numeric_or_text(column_type: str) -> bool:
    """枚举画像只对数值和短文本字段有意义。"""
    type_value = column_type.lower()
    return any(
        item in type_value
        for item in ["int", "number", "numeric", "varchar", "char", "text"]
    )


def is_time_column(name: str, column_type: str) -> bool:
    """识别可用于最近、趋势、时间排序的问题字段。"""
    normalized = normalize(name)
    type_value = column_type.lower()
    return "time" in type_value or "date" in type_value or normalized in TIME_EXACT_NAMES


def is_enum_candidate(column: dict[str, Any]) -> bool:
    """识别状态、标志、类型、等级等可能需要枚举解释的字段。"""
    name = normalize(column["name"])
    column_type = column.get("type", "").lower()
    if not is_numeric_or_text(column_type):
        return False
    if "text" in column_type:
        return False
    if name in {"yc", "sfjcyj", "aqdj", "gqpzt", "warning_level", "delete_flag"}:
        return True
    return (
        name.startswith("is")
        or name.startswith("sf")
        or name.endswith("status")
        or name.endswith("state")
        or name.endswith("flag")
        or name.endswith("type")
        or name.endswith("level")
    )


def safe_scalar(value: Any) -> str:
    """把数据库返回值转为 JSON 友好的字符串。"""
    if value is None:
        return ""
    return str(value)


def profile_table(conn, table: dict[str, Any], sample_limit: int) -> dict[str, Any]:
    """统计单表行数、字段非空率、枚举样例和时间范围。"""
    table_name = table["table_name"]
    quoted_table = quote_identifier(table_name)
    columns = table.get("fields", [])
    row_count = conn.execute(text(f"SELECT COUNT(*) AS cnt FROM {quoted_table}")).scalar() or 0

    profiled_columns = []
    for column in columns:
        column_name = column["name"]
        quoted_column = quote_identifier(column_name)
        profile = {
            "name": column_name,
            "type": column.get("type", ""),
            "business_meaning": column.get("business_meaning", ""),
            "non_null_count": None,
            "non_null_ratio": None,
            "distinct_sample": [],
            "min_value": None,
            "max_value": None,
        }

        try:
            non_null_count = conn.execute(
                text(f"SELECT COUNT({quoted_column}) AS cnt FROM {quoted_table}")
            ).scalar() or 0
            profile["non_null_count"] = int(non_null_count)
            profile["non_null_ratio"] = round(non_null_count / row_count, 4) if row_count else 0
        except Exception as exc:
            profile["profile_error"] = f"non_null_count: {exc}"

        if row_count and is_enum_candidate(column):
            try:
                if get_db_provider() == "sqlserver":
                    enum_sql = (
                        f"SELECT TOP {sample_limit} {quoted_column} AS value, COUNT(*) AS cnt "
                        f"FROM {quoted_table} "
                        f"WHERE {quoted_column} IS NOT NULL "
                        f"GROUP BY {quoted_column} "
                        f"ORDER BY cnt DESC"
                    )
                else:
                    enum_sql = (
                        f"SELECT {quoted_column} AS value, COUNT(*) AS cnt "
                        f"FROM {quoted_table} "
                        f"WHERE {quoted_column} IS NOT NULL "
                        f"GROUP BY {quoted_column} "
                        f"ORDER BY cnt DESC "
                        f"LIMIT {sample_limit}"
                    )
                enum_rows = conn.execute(
                    text(enum_sql)
                ).mappings().all()
                profile["distinct_sample"] = [
                    {"value": safe_scalar(row["value"]), "count": int(row["cnt"])}
                    for row in enum_rows
                ]
            except Exception as exc:
                profile["enum_error"] = str(exc)

        if row_count and is_time_column(column_name, column.get("type", "")):
            try:
                min_max = conn.execute(
                    text(
                        f"SELECT MIN({quoted_column}) AS min_value, "
                        f"MAX({quoted_column}) AS max_value FROM {quoted_table}"
                    )
                ).mappings().first()
                if min_max:
                    profile["min_value"] = safe_scalar(min_max["min_value"])
                    profile["max_value"] = safe_scalar(min_max["max_value"])
            except Exception as exc:
                profile["time_error"] = str(exc)

        profiled_columns.append(profile)

    populated_columns = [
        column["name"]
        for column in profiled_columns
        if column["non_null_ratio"] is not None and column["non_null_ratio"] > 0
    ]
    enum_candidates = [
        {
            "name": column["name"],
            "business_meaning": column["business_meaning"],
            "values": column["distinct_sample"],
        }
        for column in profiled_columns
        if column["distinct_sample"]
    ]

    return {
        "table_name": table_name,
        "business_domain": table.get("business_domain", ""),
        "description": table.get("description", ""),
        "row_count": int(row_count),
        "column_count": len(columns),
        "populated_column_count": len(populated_columns),
        "populated_columns": populated_columns,
        "enum_candidates": enum_candidates,
        "time_columns": [
            {
                "name": column["name"],
                "business_meaning": column["business_meaning"],
                "min_value": column["min_value"],
                "max_value": column["max_value"],
            }
            for column in profiled_columns
            if column["min_value"] or column["max_value"]
        ],
        "columns": profiled_columns,
    }


def score_core_table(table: dict[str, Any]) -> tuple[int, list[str]]:
    """根据表名、业务域和关键字段给表打分，筛选核心业务表。"""
    table_name = normalize(table["table_name"])
    field_names = {normalize(field["name"]) for field in table.get("fields", [])}
    domain = table.get("business_domain", "")
    score = 0
    reasons = []

    if table_name in HIGH_VALUE_TABLES:
        score += 40
        reasons.append("已知高切坡核心业务表")
    if table_name in SYSTEM_TABLES:
        score -= 60
        reasons.append("系统管理表，默认排除")
    if "系统管理" in domain:
        score -= 30
        reasons.append("业务域为系统管理")
    if {"gqpbh", "gqp_no", "xmbh"} & field_names:
        score += 25
        reasons.append("包含高切坡编号关联字段")
    if {"ssss", "ssqx"} & field_names:
        score += 10
        reasons.append("包含地区字段")
    if {"iscrack", "sfyls", "gqpzt", "warning_level", "sfzyjcyc", "sfsssjyc"} & field_names:
        score += 20
        reasons.append("包含异常、预警或风险相关字段")
    if {"create_time", "createdon", "review_time", "tbsj", "last_warning_date"} & field_names:
        score += 8
        reasons.append("包含时间字段")
    if table_name.startswith("geo_gqp") or table_name.startswith("tb_hcs") or "warning" in table_name:
        score += 8
        reasons.append("表名命中高切坡业务模式")
    return score, reasons


def generate_core_candidates(explained_schema: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """结合 schema 解释和真实行数，生成核心表/候选表/排除表分组。"""
    profiles = {table["table_name"]: table for table in profile["tables"]}
    candidates = []
    for table in explained_schema["tables"]:
        score, reasons = score_core_table(table)
        table_profile = profiles.get(table["table_name"], {})
        row_count = table_profile.get("row_count", 0)
        if row_count:
            score += min(12, 2 + len(str(row_count)))
            reasons.append(f"真实库有数据：{row_count} 行")
        else:
            reasons.append("真实库当前无数据或未统计到数据")

        candidates.append(
            {
                "table_name": table["table_name"],
                "business_domain": table["business_domain"],
                "description": table["description"],
                "row_count": row_count,
                "score": score,
                "recommended_level": "core" if score >= 55 else "candidate" if score >= 25 else "exclude",
                "reasons": reasons,
                "join_keys": table.get("join_keys", []),
                "query_hints": table.get("query_hints", []),
            }
        )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "core_tables": [item for item in candidates if item["recommended_level"] == "core"],
        "candidate_tables": [item for item in candidates if item["recommended_level"] == "candidate"],
        "excluded_tables": [item for item in candidates if item["recommended_level"] == "exclude"],
    }


def generate_business_starter_pack(core_candidates: dict[str, Any]) -> dict[str, Any]:
    """生成 Agent 初始业务词典、候选关系、示例 SQL 和安全约束。"""
    core_table_names = [item["table_name"] for item in core_candidates["core_tables"]]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "positioning": "高切坡数据库查询助手。优先回答真实数据库记录和统计，不替代工程专业判断。",
        "core_tables": core_table_names,
        "business_terms": [
            {
                "term": "裂缝",
                "tables": ["tb_hcs_monitoring"],
                "fields": ["isCrack", "isRead", "width", "crackImageUri"],
                "sql_hint": "isCrack = 1",
            },
            {
                "term": "落石",
                "tables": ["tb_hcs_monitoring"],
                "fields": ["sfyls"],
                "sql_hint": "sfyls = 1",
            },
            {
                "term": "异常",
                "tables": ["tb_hcs_monitoring", "geo_gqp_jbxx"],
                "fields": ["overallSituation", "hcSlopeStatus", "sfzyjcyc", "sfsssjyc", "gqpzt"],
            },
            {
                "term": "预警",
                "tables": ["t_warning_report", "t_warning_report_content", "geo_gqp_jbxx"],
                "fields": ["warning_level", "warned", "last_warning_date", "sfjcyj"],
            },
            {
                "term": "区县",
                "tables": ["geo_gqp_jbxx", "tb_hcs_monitoring", "geo_dzbjjbxx"],
                "fields": ["ssqx", "ssss"],
            },
            {
                "term": "最近",
                "tables": ["tb_hcs_monitoring", "t_warning_report", "t_review_record"],
                "fields": ["createdOn", "create_time", "review_time", "last_warning_date"],
            },
        ],
        "candidate_relations": [
            {
                "from_table": "tb_hcs_monitoring",
                "from_field": "gqpbh",
                "to_table": "geo_gqp_jbxx",
                "to_field": "gqpbh",
                "confidence": "high",
                "reason": "均为高切坡编号字段。",
            },
            {
                "from_table": "geo_dzbjjbxx",
                "from_field": "gqpbh",
                "to_table": "geo_gqp_jbxx",
                "to_field": "gqpbh",
                "confidence": "high",
                "reason": "地质背景资料通过高切坡编号关联基本信息。",
            },
            {
                "from_table": "t_warning_report_content",
                "from_field": "xmbh",
                "to_table": "geo_gqp_jbxx",
                "to_field": "gqpbh",
                "confidence": "medium",
                "reason": "xmbh 注释为项目编号（高切坡编号）。",
            },
            {
                "from_table": "geo_gqp_zyjc",
                "from_field": "gqp_no",
                "to_table": "geo_gqp_jbxx",
                "to_field": "gqpbh",
                "confidence": "medium",
                "reason": "gqp_no 表示高切坡编号。",
            },
        ],
        "query_examples": [
            {
                "question": "按区县统计高切坡数量",
                "sql": "SELECT ssqx, COUNT(*) AS count FROM geo_gqp_jbxx WHERE delete_flag = 1 GROUP BY ssqx ORDER BY count DESC",
                "tables": ["geo_gqp_jbxx"],
            },
            {
                "question": "查询最近存在裂缝或落石的高切坡",
                "sql": example_limit_sql(
                    "gqpbh, isCrack, sfyls, createdOn",
                    "FROM tb_hcs_monitoring WHERE isCrack = 1 OR sfyls = 1 ORDER BY createdOn DESC",
                ),
                "tables": ["tb_hcs_monitoring"],
            },
            {
                "question": "查询某个区县存在异常状态的高切坡",
                "sql": example_limit_sql(
                    "gqpbh, gqpmc, ssqx, gqpzt, sfzyjcyc, sfsssjyc",
                    "FROM geo_gqp_jbxx WHERE ssqx LIKE '%区县名称%' AND (gqpzt IN ('不良', '较差') OR sfzyjcyc IS NOT NULL OR sfsssjyc IS NOT NULL)",
                ),
                "tables": ["geo_gqp_jbxx"],
            },
            {
                "question": "查询最近的预警专报内容",
                "sql": example_limit_sql(
                    "title, ssqx, xmmc, xmbh, jclx, scyjsj, sfjcyj, create_time",
                    "FROM t_warning_report_content ORDER BY create_time DESC",
                ),
                "tables": ["t_warning_report_content"],
            },
            {
                "question": "查询某个高切坡的地质背景资料",
                "sql": example_limit_sql(
                    "gqpbh, gqpmc, qplx, aqdj, yxmc, fhzt, dzmc, dzms",
                    "FROM geo_dzbjjbxx WHERE gqpbh = '高切坡编号'",
                ),
                "tables": ["geo_dzbjjbxx"],
            },
        ],
        "guardrails": [
            "只生成 SELECT/WITH 查询，不执行 INSERT、UPDATE、DELETE、DROP、ALTER、TRUNCATE。",
            "系统管理表默认不用于普通业务查询。",
            "涉及风险、灾害、处置建议时，只返回数据库记录，不替代专业工程判断。",
            "枚举/标志字段优先使用真实数字或真实取值，不用中文字符串臆造比较。",
        ],
    }


def write_json(path: Path, data: Any) -> None:
    """写出格式化 JSON，便于人工校对。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    """命令行入口：画像真实表，并输出核心表候选和 starter pack。"""
    parser = argparse.ArgumentParser(description="Profile real DB tables and generate starter business knowledge.")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--starter", type=Path, default=DEFAULT_STARTER)
    parser.add_argument("--enum-limit", type=int, default=12)
    args = parser.parse_args()

    explained_schema = json.loads(args.schema.read_text(encoding="utf-8"))
    load_db_env()
    engine = create_engine(build_db_uri())
    profiles = []
    try:
        with engine.connect() as conn:
            for table in explained_schema["tables"]:
                print(f"profile {table['table_name']} ...")
                try:
                    profiles.append(profile_table(conn, table, args.enum_limit))
                except Exception as exc:
                    profiles.append(
                        {
                            "table_name": table["table_name"],
                            "business_domain": table.get("business_domain", ""),
                            "description": table.get("description", ""),
                            "row_count": None,
                            "profile_error": str(exc),
                        }
                    )
    finally:
        engine.dispose()

    profile = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "table_count": len(profiles),
        "tables": profiles,
    }
    core_candidates = generate_core_candidates(explained_schema, profile)
    starter_pack = generate_business_starter_pack(core_candidates)

    write_json(args.profile, profile)
    write_json(args.core, core_candidates)
    write_json(args.starter, starter_pack)

    print(
        json.dumps(
            {
                "profile": str(args.profile),
                "core": str(args.core),
                "starter": str(args.starter),
                "core_table_count": len(core_candidates["core_tables"]),
                "candidate_table_count": len(core_candidates["candidate_tables"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
