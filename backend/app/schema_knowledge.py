"""真实数据库 schema 知识召回。

这里暂时不接入向量数据库，而是使用导出的 schema JSON、业务词典和启发式打分，
为每次自然语言查询选择候选表，并生成注入 SQL Agent Prompt 的表字段说明。
"""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT_DIR / "backend" / "schema_exports"
EXPLAINED_SCHEMA_PATH = SCHEMA_DIR / "database_schema_explained.json"
SCHEMA_CHUNKS_PATH = SCHEMA_DIR / "schema_chunks.jsonl"
STARTER_PACK_PATH = SCHEMA_DIR / "business_starter_pack.json"
CORE_CANDIDATES_PATH = SCHEMA_DIR / "core_table_candidates.json"

# 系统管理表默认降权，避免普通业务查询误触账号、权限等无关数据。
SYSTEM_TABLES = {"t_user", "t_user_role", "t_role", "t_role_menu", "t_menus"}

# 业务关键词到核心表的人工加权，弥补纯字符串匹配对领域词的理解不足。
QUESTION_TABLE_BOOSTS = [
    (("统计", "数量", "多少", "总数", "各区县", "按区县"), ("geo_gqp_jbxx",), 45),
    (("裂缝", "落石", "群测群防", "日常监测", "巡查监测"), ("tb_hcs_monitoring",), 55),
    (("预警专报", "预警", "解除预警"), ("t_warning_report_content", "t_warning_report"), 55),
    (("复核", "审核", "24小时"), ("t_review_record",), 45),
    (("专业监测点", "监测点", "专业监测"), ("geo_gqp_zyjc",), 55),
    (("地质", "坡高", "坡长", "岩性", "风化", "安全等级"), ("geo_dzbjjbxx", "geo_gqp_jbxx"), 40),
    (("月报", "年报"), ("t_monthly",), 45),
    (("巡检报告", "险情报告", "附件"), ("t_danger_report",), 35),
]


def _load_json(path: Path, default: Any):
    """读取 JSON 文件；文件不存在时返回默认结构，方便本地冷启动。"""
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_explained_schema() -> dict[str, Any]:
    """加载带中文业务解释的真实数据库 schema。"""
    return _load_json(EXPLAINED_SCHEMA_PATH, {"tables": []})


@lru_cache(maxsize=1)
def load_starter_pack() -> dict[str, Any]:
    """加载 Agent 初始业务知识包，包括核心表、业务词、关系和样例 SQL。"""
    return _load_json(
        STARTER_PACK_PATH,
        {
            "core_tables": [],
            "business_terms": [],
            "candidate_relations": [],
            "query_examples": [],
            "guardrails": [],
        },
    )


@lru_cache(maxsize=1)
def load_core_candidates() -> dict[str, Any]:
    """加载核心表候选结果，作为缺省 include_tables 的来源。"""
    return _load_json(CORE_CANDIDATES_PATH, {"core_tables": [], "candidate_tables": []})


@lru_cache(maxsize=1)
def load_schema_chunks() -> list[dict[str, Any]]:
    """加载一个表一个 chunk 的 schema 文本，后续可替换为真正的向量召回。"""
    if not SCHEMA_CHUNKS_PATH.exists():
        return []
    chunks = []
    for line in SCHEMA_CHUNKS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            chunks.append(json.loads(line))
    return chunks


def get_table_map() -> dict[str, dict[str, Any]]:
    """按小写表名建立索引，方便召回结果回填完整表解释。"""
    return {
        table["table_name"].lower(): table
        for table in load_explained_schema().get("tables", [])
    }


def get_default_core_tables() -> list[str]:
    """获取默认核心业务表，优先使用 starter pack 中的筛选结果。"""
    starter = load_starter_pack()
    if starter.get("core_tables"):
        return starter["core_tables"]

    candidates = load_core_candidates()
    return [table["table_name"] for table in candidates.get("core_tables", [])]


def _question_terms(question: str) -> list[str]:
    """把用户问题拆成英文 token 和中文短片段，用于轻量关键词召回。"""
    terms = set()
    lowered = question.lower()
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", lowered):
        if len(token) >= 2:
            terms.add(token)

    for size in range(2, 7):
        for index in range(0, max(0, len(question) - size + 1)):
            piece = question[index : index + size].strip()
            if piece and not piece.isspace():
                terms.add(piece)

    return sorted(terms, key=len, reverse=True)


def retrieve_schema_for_question(question: str, limit: int = 8) -> list[dict[str, Any]]:
    """根据用户问题召回最相关的表解释。"""
    chunks = load_schema_chunks()
    if not chunks:
        table_map = get_table_map()
        return [table_map[name.lower()] for name in get_default_core_tables() if name.lower() in table_map]

    starter = load_starter_pack()
    boosted_tables: dict[str, int] = {}

    # 先按人工维护的业务关键词加权，再用 schema chunk 文本命中做细粒度补分。
    for keywords, table_names, boost in QUESTION_TABLE_BOOSTS:
        if any(keyword in question for keyword in keywords):
            for table_name in table_names:
                boosted_tables[table_name.lower()] = boosted_tables.get(table_name.lower(), 0) + boost

    for term in starter.get("business_terms", []):
        keyword = term.get("term", "")
        if keyword and keyword in question:
            for table_name in term.get("tables", []):
                boosted_tables[table_name.lower()] = boosted_tables.get(table_name.lower(), 0) + 30

    terms = _question_terms(question)
    scored = []
    for chunk in chunks:
        table_name = chunk.get("table_name", "")
        text = chunk.get("text", "").lower()
        score = boosted_tables.get(table_name.lower(), 0)
        for term in terms[:160]:
            if term.lower() in text:
                score += min(8, max(1, len(term) // 2))
        if table_name.lower() in {name.lower() for name in get_default_core_tables()}:
            score += 5
        if table_name.lower() in SYSTEM_TABLES:
            score -= 25
        if score > 0:
            scored.append((score, table_name))

    if not scored:
        return [
            get_table_map()[name.lower()]
            for name in get_default_core_tables()
            if name.lower() in get_table_map()
        ][:limit]

    scored.sort(reverse=True)
    table_map = get_table_map()
    selected = []
    seen = set()
    for _, table_name in scored:
        key = table_name.lower()
        if key in seen or key not in table_map:
            continue
        selected.append(table_map[key])
        seen.add(key)
        if len(selected) >= limit:
            break
    return selected


def select_include_tables(question: str) -> list[str]:
    """为 LangChain SQLDatabase 选择本次查询允许暴露的表。"""
    selected = retrieve_schema_for_question(question)
    table_names = [table["table_name"] for table in selected]
    # 基础档案表常作为 JOIN 和兜底信息来源，默认补上。
    if "geo_gqp_jbxx" not in {name.lower() for name in table_names}:
        table_names.append("geo_gqp_jbxx")
    return table_names


def _format_field(field: dict[str, Any]) -> str:
    """把字段解释压缩成适合放入 Prompt 的一行文本。"""
    parts = [
        field.get("name", ""),
        field.get("type", ""),
        field.get("business_meaning") or field.get("comment") or "",
    ]
    aliases = field.get("aliases") or []
    if aliases:
        parts.append("别名：" + "、".join(aliases[:5]))
    value_hints = field.get("value_hints") or {}
    if value_hints:
        parts.append("取值：" + "；".join(f"{key}={value}" for key, value in value_hints.items()))
    usage_hint = field.get("usage_hint")
    if usage_hint:
        parts.append(usage_hint)
    return " / ".join(part for part in parts if part)


def build_schema_guide(question: str, field_limit: int = 28) -> str:
    """构造注入 SQL Agent 的 schema 业务说明。"""
    tables = retrieve_schema_for_question(question)
    starter = load_starter_pack()
    sections = [
        "以下为根据用户问题从真实数据库 schema 知识库中召回的候选表，优先使用这些表和字段生成 SQL："
    ]

    for table in tables:
        fields = table.get("fields", [])
        important_fields = []
        # 优先展示有别名、枚举、主键、查询提示的字段，避免 Prompt 被低价值字段撑满。
        for field in fields:
            if (
                field.get("value_hints")
                or field.get("usage_hint")
                or field.get("primary_key")
                or field.get("aliases")
                or field.get("comment")
            ):
                important_fields.append(field)
        if len(important_fields) < min(field_limit, len(fields)):
            for field in fields:
                if field not in important_fields:
                    important_fields.append(field)
                if len(important_fields) >= field_limit:
                    break

        sections.append(
            "\n".join(
                [
                    f"- 表 {table['table_name']}（{table.get('business_domain', '未分类')}）：{table.get('description', '')}",
                    f"  别名：{'、'.join(table.get('aliases', [])) or '无'}",
                    f"  关联键：{', '.join(table.get('join_keys', [])) or '待确认'}",
                    "  关键字段：",
                    *[f"    - {_format_field(field)}" for field in important_fields[:field_limit]],
                    "  查询提示：",
                    *[f"    - {hint}" for hint in table.get("query_hints", [])],
                ]
            )
        )

    business_terms = []
    for term in starter.get("business_terms", []):
        keyword = term.get("term", "")
        if keyword and keyword in question:
            business_terms.append(
                f"- {keyword}: 表={','.join(term.get('tables', []))}; 字段={','.join(term.get('fields', []))}; SQL提示={term.get('sql_hint', '')}"
            )
    if business_terms:
        sections.append("命中的业务词典：\n" + "\n".join(business_terms))

    relations = starter.get("candidate_relations", [])
    if relations:
        sections.append(
            "候选表关系：\n"
            + "\n".join(
                f"- {item['from_table']}.{item['from_field']} -> {item['to_table']}.{item['to_field']}（{item.get('confidence', '')}，{item.get('reason', '')}）"
                for item in relations
            )
        )

    examples = starter.get("query_examples", [])
    if examples:
        sections.append(
            "可参考的查询样例：\n"
            + "\n".join(
                f"- 问：{item['question']}\n  SQL：{item['sql']}"
                for item in examples[:5]
            )
        )

    guardrails = starter.get("guardrails", [])
    if guardrails:
        sections.append("约束：\n" + "\n".join(f"- {item}" for item in guardrails))

    return "\n\n".join(sections)
