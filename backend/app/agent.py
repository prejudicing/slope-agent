"""高切坡智能查询 Agent 主流程。

本模块负责把用户自然语言问题交给 LangChain SQL Agent，实时推送思考过程，
并把最后一次成功执行的 SQL 结果重新整理成前端可展示的表格。
"""

import io
import json
import queue
import re
import threading
from collections import Counter
from contextlib import redirect_stdout
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from langchain_openai import ChatOpenAI
from langchain_community.agent_toolkits import create_sql_agent

try:
    from langchain_core.callbacks import BaseCallbackHandler
except Exception:
    BaseCallbackHandler = object

from app.db import get_db
from app.business_queries import enrich_rows, get_deterministic_query
from app.monitoring_scale import get_county_monitoring_scale
from app.report_inventory import get_report_asset_inventory
from app.sqlserver_db import query_sqlserver_for_display
from app.config import (
    QUERY_API_KEY,
    QUERY_BASE_URL,
    QUERY_MODEL,
    QUERY_PROVIDER,
    QUERY_THINKING_ENABLED,
    REPORT_API_KEY,
    REPORT_BASE_URL,
    REPORT_MODEL,
    REPORT_PROVIDER,
    REPORT_REASONING_EFFORT,
    REPORT_THINKING_ENABLED,
    HCS_QMQF_SOURCE,
    DM_HOST,
    DM_PASSWORD,
    DM_PORT,
    DM_USER,
)
from app.conversation_context import (
    normalize_history,
    resolve_effective_question,
)
from app.domain import GQP_AGENT_PREFIX
from app.query_cache import get_cached_sql, save_cached_sql
from app.photo_service import find_photo_attachments
from app.photo_service import build_photo_summary, has_photo_intent, search_photo_records
from app.question_normalizer import normalize_query_question
from app.query_router import QueryRouteDecision, route_question
from app.schema_knowledge import build_schema_guide, select_include_tables


# 只允许只读查询。这里用黑名单拦截常见写操作，真正执行前还会再次检查。
FORBIDDEN_SQL_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|MERGE|CALL|EXEC)\b",
    re.IGNORECASE,
)
PARSING_ERROR_OUTPUT_RE = re.compile(
    r"Could not parse LLM output:\s*`(.+?)`\s*For troubleshooting",
    re.DOTALL,
)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
SCHEMA_DDL_RE = re.compile(
    r'CREATE TABLE\s+".+?"\s*\(.+?\)\s*(?:/\*.*?\*/)?',
    re.DOTALL | re.IGNORECASE,
)
USER_FACING_SQL_RE = re.compile(
    r"```sql.*?```|(?:SELECT|WITH)\s+.+?(?:FROM|JOIN)\s+.+?(?=(?:\n\n|$))",
    re.DOTALL | re.IGNORECASE,
)
STREAM_DONE = object()
DISPLAY_ROW_LIMIT = 50


def _mask_base_url(base_url: str | None) -> str:
    if not base_url:
        return ""
    return base_url.rstrip("/")


def _log_llm_selection(
    *,
    stage: str,
    provider: str,
    model: str,
    base_url: str | None,
    thinking_enabled: bool,
    reasoning_effort: str | None = None,
) -> None:
    parts = [
        f"provider={provider or 'auto'}",
        f"model={model}",
    ]
    if base_url:
        parts.append(f"base_url={_mask_base_url(base_url)}")
    parts.append(f"thinking={'on' if thinking_enabled else 'off'}")
    if reasoning_effort:
        parts.append(f"reasoning_effort={reasoning_effort}")
    print(f">>> [{stage}_llm] {' '.join(parts)}")


def build_non_query_result(question: str, decision: QueryRouteDecision) -> dict:
    """把拒答/澄清类路由结果整理成与查询结果兼容的固定响应结构。"""
    summary = (decision.summary or "").strip()
    if decision.suggestion:
        summary = f"{summary}\n\n{decision.suggestion}"
    return {
        "status": decision.status,
        "query_type": decision.query_type,
        "question": question,
        "sql": "",
        "result": summary,
        "summary": summary,
        "report": None,
        "suggestion": decision.suggestion,
        "columns": [],
        "rows": [],
        "total_rows": 0,
        "attachments": [],
        "logs": f"问题路由结果：{decision.reason}",
        "error": None,
    }


def sanitize_query_result(result: dict) -> dict:
    """Remove internal SQL/log details from user-facing API payloads."""
    cleaned = dict(result or {})
    cleaned["sql"] = ""
    cleaned["logs"] = ""
    for key in ("result", "summary", "suggestion"):
        if cleaned.get(key):
            cleaned[key] = scrub_user_facing_text(str(cleaned[key]))
    if cleaned.get("error"):
        cleaned["error"] = "本次查询未能生成有效业务回答，请调整问题后重试。"
    return cleaned


def scrub_user_facing_text(text_value: str) -> str:
    """清理面向用户的回答，避免泄露 SQL、内部执行路径或过程性说明。"""
    text_value = USER_FACING_SQL_RE.sub("相关明细已整理在结果表中。", text_value or "")
    replacements = {
        "真实 SQL 查询结果表": "结果表",
        "真实查询结果表": "结果表",
        "SQL 查询结果": "结果",
        "SQL": "查询语句",
        "查询口径": "统计范围",
        "生成来源": "资料范围",
        "Agent": "系统",
        "模板路由": "业务规则",
    }
    for old, new in replacements.items():
        text_value = text_value.replace(old, new)
    return re.sub(r"\n{3,}", "\n\n", text_value).strip()


def user_friendly_error_message(error: Exception | str) -> str:
    """把内部异常改写成前端可展示的业务提示。"""
    text_value = str(error or "")
    internal_markers = (
        "Missing credentials",
        "OPENAI_API_KEY",
        "OPENAI_ADMIN_KEY",
        "api_key",
        "workload_identity",
        "admin_api_key",
        "Traceback",
        "LangChain",
        "ChatOpenAI",
    )
    if any(marker in text_value for marker in internal_markers):
        return "本次问题未能进入稳定业务查询模板，系统暂时无法生成可靠回答。请换成更明确的业务问题，例如“近期哪个区县高切坡风险较高”“近期专业监测情况”或“近期群测群防情况”。"
    return "本次查询未能生成有效业务回答，请补充区县、编号、监测类型、异常类型或时间范围后重试。"


def append_followup_guidance(summary: str, query_name: str = "", question: str = "") -> str:
    """在业务回答末尾补充下一步可追问方向。"""
    summary = (summary or "").strip()
    if not summary:
        return summary
    if "需要我继续" in summary or "需要我给出" in summary or "是否需要我" in summary:
        return summary

    compact = "".join((question or "").split())
    guidance_map = {
        "recent_risk_county": "需要我继续给出重点区县的异常高切坡清单、现场照片复核意见或处置优先顺序吗？",
        "recent_monitoring_abnormal": "需要我继续给出异常记录明细、对应现场照片标注或按区县汇总的复核清单吗？",
        "focus_slope_attention": "需要我继续给出这些高切坡的现场照片、联系人和复核建议清单吗？",
        "recent_large_displacement": "需要我继续给出具体高切坡的监测点年度位移曲线、月度变化表或稳定性评价吗？",
        "recent_slope_brief": "需要我继续生成按区县展开的明细清单、现场复核对象或可下载的业务简报吗？",
        "county_overview": "需要我继续给出该区县的重点高切坡清单、专业监测变化情况或群测群防异常记录吗？",
        "county_monitoring_scale": "需要我继续按区县展开专业监测坡清单、监测点清单或群测群防记录明细吗？",
        "report_asset_inventory": "需要我继续按区县展开月报照片清单、专业监测点关系表或稳定性评价明细吗？",
        "personnel_info": "需要我继续按角色、区县或联系方式完整性筛选人员名单吗？",
        "abnormal_type": "需要我继续按异常类型、区县或高切坡名称展开明细吗？",
        "county_abnormal_compare": "需要我继续给出各区县异常对象清单或近期变化较突出的高切坡吗？",
        "report_displacement_charts": "需要我继续给出具体监测点曲线、月报评价摘录或高切坡稳定性分析吗？",
    }
    guidance = guidance_map.get(query_name, "")
    if not guidance:
        if "群测群防" in compact or "现场" in compact or "照片" in compact:
            guidance = "需要我继续给出现场异常照片、细项异常记录或复核建议清单吗？"
        elif "专业监测" in compact or "位移" in compact or "曲线" in compact:
            guidance = "需要我继续给出监测点曲线、年度位移变化表或稳定性评价吗？"
        elif "风险" in compact or "异常" in compact or "预警" in compact:
            guidance = "需要我继续给出风险对象清单、区县排序或处置建议吗？"
        elif "高切坡" in compact:
            guidance = "需要我继续给出高切坡明细、监测情况或现场复核对象吗？"
    if not guidance:
        guidance = "需要我继续按区县、编号、监测类型或时间范围进一步展开吗？"
    return f"{summary}\n\n{guidance}"


def classify_answer_layer(question: str, query_name: str = "") -> str:
    """按用户问法确定回答层级：单点研判、业务简报或明细清单。"""
    compact = "".join((question or "").split())
    if any(keyword in compact for keyword in ("简报", "报告", "汇报", "业务情况", "总体情况", "综合情况")):
        return "business_brief"
    if any(keyword in compact for keyword in ("明细", "清单", "列表", "列出", "逐项", "详细", "表格", "下载", "台账")):
        return "detail_list"
    if any(keyword in compact for keyword in ("哪个", "哪一个", "最", "是否", "能否", "有没有", "多少", "主要", "重点关注", "需要关注")):
        return "single_judgement"
    if query_name in {"recent_slope_brief"}:
        return "business_brief"
    if query_name in {"qmqf_review_list", "focus_slope_attention", "personnel_info", "county_monitoring_scale", "report_asset_inventory", "abnormal_type", "county_abnormal_compare"}:
        return "detail_list"
    if query_name in {"recent_risk_county", "county_overview"}:
        return "single_judgement"
    return "business_brief"


def enrich_photo_attachments(question: str, rows: list[dict]) -> list[dict]:
    """按需从 SQL Server 照片库补充现场照片附件，不影响主查询成功返回。"""
    try:
        return find_photo_attachments(question, rows)
    except Exception as exc:
        print(f">>> [photo_attachments] skipped: {exc}")
        return []


def extract_sql_from_logs(log_text: str) -> str:
    """从 Agent verbose 日志里兜底提取 SQL。

    正常情况下优先使用 callback 记录的 sql_db_query；该函数主要用于异常场景兜底。
    """
    log_text = ANSI_RE.sub("", log_text)
    patterns = [
        r'Action Input:\s*"((?:SELECT|WITH).*?)"',
        r'Action Input:\s*```sql\s*(.*?)\s*```',
        r'```sql\s*(.*?)\s*```',
        r'Action Input:\s*((?:SELECT|WITH)\b.*?)(?=\n(?:Action:|Observation:|Final Answer:|> Finished|\Z))',
    ]

    matches = []
    for pattern in patterns:
        found = re.findall(pattern, log_text, flags=re.IGNORECASE | re.DOTALL)
        if found:
            matches.extend(found)

    if not matches:
        return ""

    return normalize_sql(matches[-1])


def normalize_sql(sql: str) -> str:
    """清理模型或日志中常见的 SQL 包裹字符，避免回查表格时执行失败。"""
    sql = sql.strip()
    sql = sql.strip("`")
    sql = sql.replace('\\"', '"').replace("\\n", "\n")
    sql = re.sub(r"^sql\s+", "", sql.strip(), flags=re.IGNORECASE)
    sql = re.sub(r";\s*$", "", sql.strip())
    return sql


def extract_answer_from_parsing_error(error_text: str) -> str:
    """LangChain 输出解析失败时，从异常文本中恢复模型已经生成的中文答案。"""
    match = PARSING_ERROR_OUTPUT_RE.search(error_text)
    if not match:
        return ""
    answer = match.group(1).strip()
    return answer.replace("\\n", "\n")


def _serialize_cell(value) -> str:
    if value is None:
        return ""
    return str(value)


def _safe_int(value) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return 0


def query_table_for_display(
    db,
    sql: str,
    display_limit: int = DISPLAY_ROW_LIMIT,
) -> tuple[list[str], list[dict], int]:
    """用最终 SQL 重新查询一次数据库，生成前端 ResultPanel 需要的 columns/rows。

    页面只展示前若干条样本，但仍单独统计总条数，避免大结果集把前端压垮。
    """
    sql = normalize_sql(sql)
    if not sql or FORBIDDEN_SQL_RE.search(sql):
        return [], [], 0

    engine = getattr(db, "_engine", None)
    if engine is None:
        return [], [], 0

    try:
        with engine.connect() as conn:
            total_rows = 0
            try:
                count_sql = f"SELECT COUNT(*) AS total_count FROM ({sql}) result_count_subquery"
                total_rows = int(conn.execute(text(count_sql)).scalar() or 0)
            except Exception:
                total_rows = 0

            result = conn.execute(text(sql))
            columns = list(result.keys())
            rows = [
                {column: _serialize_cell(row[column]) for column in columns}
                for row in result.mappings().fetchmany(display_limit)
            ]
        return columns, rows, total_rows or len(rows)
    except Exception:
        return [], [], 0


def build_cached_summary(rows: list[dict], total_rows: int) -> str:
    """复用缓存 SQL 时生成稳定摘要，不再让 LLM 重新改写答案。"""
    if total_rows:
        return (
            "已形成查询结果。"
            f"本次共整理 {total_rows} 条记录，页面展示其中 {len(rows)} 条主要明细。"
            "相关对象、数量和状态见明细表。"
        )
    return (
        "暂未检索到符合条件的记录。建议补充区县、编号、监测类型、异常类型或时间范围后再查询。"
    )


def build_template_summary(query_name: str, summary: str, rows: list[dict], total_rows: int, question: str = "") -> str:
    sample_text = f"页面展示 {len(rows)} 条主要明细。"
    answer_layer = classify_answer_layer(question, query_name)
    if query_name == "county_monitoring_scale":
        if not rows:
            return "暂未查询到可用于区县监测规模统计的数据。"
        detail_rows = [row for row in rows if "合计" not in str(row.get("区县") or "")]
        total_row = next((row for row in rows if "业务核定" in str(row.get("区县") or "")), {})
        total_slope = _safe_int(total_row.get("高切坡总数")) or sum(_safe_int(row.get("高切坡总数")) for row in detail_rows)
        total_qmqf = _safe_int(total_row.get("群测群防高切坡数量")) or total_slope
        total_qmqf_records = sum(_safe_int(row.get("群测群防监测记录数")) for row in detail_rows)
        total_professional = _safe_int(total_row.get("专业监测高切坡数量")) or sum(_safe_int(row.get("专业监测高切坡数量")) for row in detail_rows)
        top_counties = "、".join(
            f"{row.get('区县')}（高切坡{row.get('高切坡总数', 0)}处，专业监测点{row.get('专业监测点数量', 0)}个）"
            for row in detail_rows[:3]
        )
        return (
            "湖北四县区高切坡监测规模已完成统计。"
            f"本次统计涉及兴山县、巴东县、秭归县、夷陵区 4 个区县，高切坡业务核定总数为 {total_slope} 处；"
            f"台账内高切坡均纳入群测群防管理，群测群防高切坡 {total_qmqf} 处，形成监测记录 {total_qmqf_records} 条；"
            f"其中专业监测高切坡 {total_professional} 处，属于群测群防管理对象中的重点监测子集。"
            f"分区县明细显示，数量相对集中的区县包括{top_counties}。"
            "明细表同步列出各区县监测规模，可用于台账复核和业务统计。"
        )
    if query_name == "report_asset_inventory":
        if not rows:
            return "暂未形成可用于展示的月报内容清单。"
        total_docs = sum(_safe_int(row.get("月报份数")) for row in rows)
        total_xyh = sum(_safe_int(row.get("XYH月度记录")) for row in rows)
        total_photos = sum(_safe_int(row.get("现场照片")) for row in rows)
        total_stability = sum(_safe_int(row.get("稳定性评价")) for row in rows)
        top_text = "、".join(
            f"{row.get('区县')}（月报{row.get('月报份数', 0)}份，监测点{row.get('监测点数量', 0)}个）"
            for row in rows[:4]
        )
        return (
            "月报内容已按区县形成结构化清单。"
            f"当前已整理 {total_docs} 份月报，沉淀专业监测 XYH 月度记录 {total_xyh} 条、"
            f"现场照片 {total_photos} 张、稳定性评价 {total_stability} 条。"
            f"从已整理内容看，{top_text}。"
            "后续可继续围绕专业监测坡与监测点关系、月度位移曲线、现场照片和稳定性评价开展复核。"
        )
    if query_name == "personnel_info":
        if not rows:
            return "未查询到符合条件的人员信息。人员信息查询仅展示业务联系字段，不返回密码、证件号、IP、重置密钥等敏感内容。"
        roles = Counter(str(row.get("角色") or "未标注角色") for row in rows)
        counties = Counter(str(row.get("所属区县") or "未标注区县") for row in rows)
        county_text = "、".join(f"{county}{count}人" for county, count in counties.most_common(3) if county != "未标注区县")
        county_sentence = f"；从区县看，主要涉及{county_text}" if county_text else ""
        return (
            f"本次共整理 {total_rows} 名人员信息，页面列示 {len(rows)} 名。"
            f"从角色看，主要包括{ '、'.join(f'{role}{count}人' for role, count in roles.most_common(4)) }{county_sentence}。"
            "明细表按人员姓名、登录账号、角色、所属区县、部门职务和联系方式展示，已屏蔽密码、证件号、登录 IP 等敏感信息。"
        )
    if query_name == "county_overview":
        row = rows[0] if rows else {}
        county = row.get("区县") or "该区县"
        total = row.get("高切坡数量", 0)
        professional_slopes = row.get("专业监测高切坡数量", 0)
        professional_points = row.get("专业监测点数量", 0)
        professional_abnormal = row.get("专业监测异常标记数量", 0)
        qmqf_abnormal = row.get("群测群防异常标记数量", 0)
        return (
            f"{county}高切坡总体纳入基础台账管理 {total} 处，专业监测覆盖 {professional_slopes} 处、"
            f"监测点 {professional_points} 个。当前基础资料中专业监测异常标记 {professional_abnormal} 处，"
            f"群测群防异常标记 {qmqf_abnormal} 处。总体看，该区高切坡以常态化监测和巡查复核为主，"
            "后续应重点关注专业监测连续位移变化对象和近期现场异常记录，及时核查裂缝、落石、挡墙开裂等局部问题。"
        )
    if query_name == "recent_risk_county":
        if not rows:
            return "近期暂未识别到可用于区县风险研判的专业监测数据。"
        qmqf_context = _build_qmqf_risk_context()
        report_notes = _fetch_latest_stability_notes([str(row.get("区县") or "") for row in rows[:4]])
        top = rows[0]
        top_county = top.get("区县") or "相关区县"
        attention = top.get("需关注高切坡数量", 0)
        slope = top.get("代表性高切坡") or "代表性高切坡"
        code = top.get("代表性高切坡编号") or ""
        change = top.get("代表性高切坡位移变化量_mm", 0)
        monthly_change = top.get("代表性高切坡最大单月位移_mm", top.get("最大单月位移变化量_mm", 0))
        top_county = qmqf_context.get("top_county") or top_county
        qmqf_sentence = qmqf_context.get("top_sentence") or f"{top_county}近期现场异常相对集中，应作为首要复核区县。"
        if answer_layer == "single_judgement":
            pieces = [
                f"近期高切坡风险研判中，{top_county}相对需要优先关注。",
                qmqf_sentence,
                f"专业监测方面，{slope}{f'（{code}）' if code else ''}存在持续小幅位移，年度累计变化量约 {change} mm，最大单月变化量约 {monthly_change} mm；该指标作为辅助判断，不单独等同于风险等级。",
            ]
        else:
            pieces = [
                f"近期高切坡风险研判中，{top_county}相对需要优先关注。",
                qmqf_sentence,
                f"专业监测结果显示，{top.get('区县') or '相关区县'}部分坡体存在持续小幅位移，其中{slope}{f'（{code}）' if code else ''}年度累计变化量约 {change} mm，最大单月变化量约 {monthly_change} mm，暂不宜仅据该指标判定为高风险。",
            ]
        if report_notes:
            pieces.append("综合现有巡查与稳定性评价，当前未见普遍性失稳迹象。")
        pieces.append(f"建议近期以{top_county}为重点开展现场复核，同步观察连续位移变化对象；若后续出现裂缝扩展、落石增多或监测点加速变形，再相应提高处置等级。")
        return "".join(pieces)
    if query_name == "abnormal_type":
        return f"{summary} 本次共整理 {total_rows} 条异常记录，异常类型见明细表。"
    if query_name == "recent_monitoring_abnormal":
        qmqf_context = _build_qmqf_risk_context()
        if answer_layer == "detail_list":
            return (
                "近期群测群防异常明细已整理。"
                f"{qmqf_context.get('sentence') or '当前异常记录未形成明显区县集中趋势。'}"
                "明细重点包括高切坡名称、区县、异常类型、记录时间、联系人和现场照片，适合用于现场复核分派。"
            )
        return (
            "近期群测群防监测以现场异常复核为重点。"
            f"{qmqf_context.get('sentence') or '当前未形成明显区县集中趋势。'}"
            "建议对涉及落石、挡墙开裂、坡面破坏和有明确裂缝数值的记录优先开展现场复核；"
            "对仅有照片或描述异常但缺少量测值的对象，应结合原始照片和巡查记录进一步确认。"
        )
    if query_name == "qmqf_review_list":
        if not rows:
            return "近期暂未形成可展示的群测群防异常复核清单。"
        counties = Counter(str(row.get("所属区县") or "未标注区县") for row in rows)
        review_types = Counter(str(row.get("复核类型") or "持续跟踪") for row in rows)
        top_items = "；".join(
            f"{row.get('所属区县') or '未标注区县'}{row.get('高切坡名称') or row.get('高切坡编号')}（{row.get('异常内容') or '异常记录'}）"
            for row in rows[:3]
        )
        return (
            f"近期群测群防异常复核清单已生成，共整理 {total_rows} 条记录。"
            f"从区县分布看，主要涉及{ '、'.join(f'{county}{count}处' for county, count in counties.most_common(4)) }；"
            f"从复核类型看，主要包括{ '、'.join(f'{name}{count}处' for name, count in review_types.most_common(4)) }。"
            f"代表性对象包括：{top_items}。建议按清单优先核实有落石、坡面破坏、道路或挡墙开裂等明显异常的对象，"
            "同步补充现场照片、异常部位描述和复核处置记录。"
        )
    if query_name == "focus_slope_attention":
        qmqf_context = _build_qmqf_risk_context()
        sentence = qmqf_context.get("top_sentence") or qmqf_context.get("sentence") or "近期需关注对象以现场异常记录较明确的高切坡为主。"
        return (
            "近期值得重点关注的高切坡，应优先从现场异常较明确、照片佐证较充分、且存在落石、裂缝、挡墙开裂或坡面破坏等情况的对象中筛选。"
            f"{sentence}"
            "对上述对象建议先开展现场复核，核实异常部位是否持续发展；同时结合专业监测位移曲线判断是否存在同步变化。"
            "页面下方已按高切坡对象展示近期异常记录、现场照片和联系人，便于形成复核清单。"
        )
    if query_name == "recent_slope_brief":
        report_context = _build_report_stability_context()
        if answer_layer == "single_judgement":
            return (
                "近期高切坡总体处于常态化监测管理状态，尚未形成普遍性失稳迹象。"
                "当前应优先复核现场照片反映较明显、多项异常叠加或专业监测持续变化的局部对象。"
                f"{report_context}"
            )
        return (
            "近期高切坡总体处于常态化监测管理状态，局部对象需结合现场异常和专业监测变化持续跟踪。"
            "当前工作重点包括：复核群测群防发现的落石、裂缝、挡墙开裂等现场问题；关注专业监测中连续小幅位移变化的坡体；"
            "对照片反映较明显、多项异常叠加或专业监测持续变化的对象，及时组织现场核查并形成处置记录。"
            f"{report_context}"
        )
    if query_name == "recent_large_displacement":
        monitor_context = _build_professional_monitor_context()
        if answer_layer == "single_judgement":
            return (
                "近期专业监测结果总体未显示普遍性失稳迹象，需重点跟踪位移变化相对突出的个别坡体。"
                f"{monitor_context}"
                "建议先观察同一坡体多个监测点是否同步增大，再决定是否提高关注等级。"
            )
        if answer_layer == "detail_list":
            return (
                "近期专业监测重点对象已整理。"
                f"{monitor_context}"
                "下方卡片展示监测点、年度位移变化量、月均变化速率、联系人、现场照片和位移变化图。"
            )
        return (
            "近期专业监测结果总体未显示普遍性失稳迹象，但部分坡体存在连续小幅位移变化，应纳入跟踪。"
            f"{monitor_context}"
            "建议结合现场照片和后续监测曲线持续复核；如同一坡体多个监测点出现同步增大或连续加速，再提高关注等级。"
        )
    if query_name == "report_displacement_charts":
        return (
            f"{summary} 本次共整理 {total_rows} 条专业监测曲线相关记录。"
            "展示内容以各区县近期成果为主，历史资料用于趋势复核。"
        )
    if query_name == "county_abnormal_compare":
        return f"{summary} 本次共统计 {total_rows} 个区县。"
    return f"{summary} 本次共整理 {total_rows} 条记录，{sample_text}"


def _build_qmqf_risk_context() -> dict:
    try:
        from app.qmqf_dashboard import get_qmqf_abnormal_dashboard

        dashboard = get_qmqf_abnormal_dashboard(20)
        items = dashboard.get("items") or []
    except Exception as exc:
        return {"sentence": f"群测群防数据暂时读取失败，需人工复核现场异常记录（{exc}）。"}
    if not items:
        return {"sentence": "群测群防近期未检索到有效异常记录。"}

    counts = Counter(str(item.get("ssqx") or "未标注区县") for item in items)
    top_county, top_count = counts.most_common(1)[0]
    samples = [
        item for item in items
        if str(item.get("ssqx") or "未标注区县") == top_county
    ][:3]
    sample_text = "、".join(
        f"{item.get('gqpmc') or item.get('gqpbh')}（{item.get('abnormal_summary') or '异常记录'}）"
        for item in samples
    )
    other_text = "、".join(f"{county}{count}处" for county, count in counts.most_common(4)[1:])
    top_sentence = f"{top_county}发现 {top_count} 处代表性现场异常，涉及{sample_text}。"
    sentence = f"{top_county}发现 {top_count} 处代表性现场异常，涉及{sample_text}。"
    if other_text:
        sentence += f"其余异常记录分布于{other_text}。"
    return {"top_county": top_county, "sentence": sentence, "top_sentence": top_sentence}


def _build_professional_monitor_context() -> str:
    try:
        from app.displacement_dashboard import get_recent_displacement_dashboard

        dashboard = get_recent_displacement_dashboard(4)
        items = dashboard.get("items") or []
    except Exception:
        return "暂未形成可用于排序的专业监测重点对象。"
    if not items:
        return "暂未形成可用于排序的专业监测重点对象。"

    top = items[0]
    county = top.get("ssqx") or "相关区县"
    name = top.get("gqpmc") or top.get("gqpbh") or "代表性高切坡"
    code = top.get("gqpbh") or ""
    point = (top.get("stability") or {}).get("top_point") or "-"
    change = top.get("max_recent_change", 0)
    rate = top.get("avg_monthly_rate") or (top.get("stability") or {}).get("avg_monthly_rate") or 0
    others = "、".join(
        f"{item.get('ssqx') or ''}{item.get('gqpmc') or item.get('gqpbh')}（{item.get('max_recent_change', 0)}mm）"
        for item in items[1:4]
    )
    text = (
        f"其中，{county}{name}{f'（{code}）' if code else ''}的监测点{point}年度累计位移变化量约 {change} mm，"
        f"月均变化速率约 {rate} mm/月。"
    )
    if others:
        text += f"其他需跟踪对象包括{others}。"
    return text


def _build_report_stability_context() -> str:
    try:
        from app.report_assets import get_recent_report_stability_assets

        payload = get_recent_report_stability_assets(limit=6, only_with_photos=True)
        items = payload.get("items") or []
    except Exception:
        items = []
    if not items:
        return ""
    levels = Counter(item.get("stability_level") or "待复核" for item in items)
    top = items[0]
    name = top.get("gqpmc") or top.get("gqpbh") or "相关高切坡"
    county = top.get("county") or ""
    keywords = top.get("abnormal_keywords") or top.get("stability_level") or "现场异常"
    return (
        f"{county}{name}涉及{keywords}，建议纳入现场复核对象；"
        f"当前复核样本中{', '.join(f'{key}{value}处' for key, value in levels.items())}。"
    )


def _fetch_latest_stability_notes(counties: list[str]) -> list[str]:
    counties = [county for county in dict.fromkeys(counties) if county]
    if not counties:
        return []
    engine = create_engine(f"dm+dmPython://{DM_USER}:{quote_plus(DM_PASSWORD)}@{DM_HOST}:{DM_PORT}/")
    try:
        notes: list[str] = []
        with engine.connect() as conn:
            for county in counties:
                rows = conn.execute(text("""
SELECT report_month, chunk_index, content
FROM ai_monthly_report_chunk
WHERE county = :county
  AND report_year = 2025
ORDER BY report_month DESC NULLS LAST, chunk_index ASC
FETCH FIRST 16 ROWS ONLY
"""), {"county": county}).mappings().all()
                for row in rows:
                    content = str(row.get("content") or "")
                    snippet = _extract_stability_sentence(content)
                    if snippet:
                        notes.append(f"{county}{int(row.get('report_month') or 0)}月月报：{snippet}")
                        break
        return notes
    except Exception:
        return []
    finally:
        engine.dispose()


def _extract_stability_sentence(content: str) -> str:
    normalized = re.sub(r"\s+", "", content or "")
    for keyword in ("总体较为稳定", "总体稳定", "尚无异常", "无异常现象", "较为稳定", "基本稳定"):
        index = normalized.find(keyword)
        if index >= 0:
            start = max(
                normalized.rfind("。", 0, index),
                normalized.rfind("；", 0, index),
                normalized.rfind("：", 0, index),
                normalized.rfind("\n", 0, index),
            )
            end_candidates = [
                pos for pos in (
                    normalized.find("。", index),
                    normalized.find("；", index),
                    normalized.find("\n", index),
                )
                if pos >= 0
            ]
            start = 0 if start < 0 else start + 1
            end = min(end_candidates) + 1 if end_candidates else min(len(normalized), index + 80)
            sentence = normalized[start:end]
            return sentence[:180]
    return ""


def _build_chat_llm(
    *,
    model: str,
    api_key: str | None,
    base_url: str | None,
    provider: str,
    thinking_enabled: bool,
    reasoning_effort: str | None = None,
) -> ChatOpenAI:
    """创建 OpenAI 兼容聊天模型，并按需注入 DeepSeek thinking 配置。"""
    llm_kwargs = {
        "model": model,
        "temperature": 0,
        "api_key": api_key,
    }
    if base_url:
        llm_kwargs["base_url"] = base_url

    # 优先尊重显式 provider 配置，避免 GPT 走中转站时被域名误判。
    # provider=auto 时再退回到基于模型名 / base_url 的轻量识别。
    provider_hint = f"{model} {base_url or ''}".lower()
    normalized_provider = (provider or "auto").strip().lower()
    if normalized_provider == "deepseek":
        is_deepseek_compatible = True
    elif normalized_provider == "openai":
        is_deepseek_compatible = False
    else:
        is_deepseek_compatible = "deepseek" in provider_hint

    # thinking / reasoning_effort 目前按 DeepSeek 兼容接口接入。
    # GPT 即使走第三方中转站，也不应发送这些 DeepSeek 专有参数。
    if is_deepseek_compatible:
        llm_kwargs["extra_body"] = {
            "thinking": {"type": "enabled" if thinking_enabled else "disabled"}
        }
        if reasoning_effort:
            llm_kwargs["reasoning_effort"] = reasoning_effort

    return ChatOpenAI(**llm_kwargs)


def build_query_llm() -> ChatOpenAI:
    """查询阶段模型：默认关闭 thinking，优先保证工具调用和 SQL 结果稳定。"""
    _log_llm_selection(
        stage="query",
        provider=QUERY_PROVIDER,
        model=QUERY_MODEL,
        base_url=QUERY_BASE_URL,
        thinking_enabled=QUERY_THINKING_ENABLED,
    )
    return _build_chat_llm(
        model=QUERY_MODEL,
        api_key=QUERY_API_KEY,
        base_url=QUERY_BASE_URL,
        provider=QUERY_PROVIDER,
        thinking_enabled=QUERY_THINKING_ENABLED,
    )


def build_report_llm() -> ChatOpenAI | None:
    """报告阶段模型：允许开启 thinking，但限制在 high 级别。"""
    if not REPORT_API_KEY:
        print(">>> [report_llm] skipped: missing api key")
        return None
    _log_llm_selection(
        stage="report",
        provider=REPORT_PROVIDER,
        model=REPORT_MODEL,
        base_url=REPORT_BASE_URL,
        thinking_enabled=REPORT_THINKING_ENABLED,
        reasoning_effort=REPORT_REASONING_EFFORT if REPORT_THINKING_ENABLED else None,
    )
    return _build_chat_llm(
        model=REPORT_MODEL,
        api_key=REPORT_API_KEY,
        base_url=REPORT_BASE_URL,
        provider=REPORT_PROVIDER,
        thinking_enabled=REPORT_THINKING_ENABLED,
        reasoning_effort=REPORT_REASONING_EFFORT if REPORT_THINKING_ENABLED else None,
    )


def analyze_query_result(
    llm: ChatOpenAI | None,
    question: str,
    sql: str,
    columns: list[str],
    rows: list[dict],
    total_rows: int,
    fallback: str = "",
    mode: str = "db_query",
) -> str:
    """把真实查询结果表交给 LLM 生成业务报告。

    这里的 LLM 只做“读表分析”，不再决定查询哪些表或字段。
    """
    if llm is None:
        return fallback or build_cached_summary(rows, total_rows)

    if not columns:
        return (
            fallback
            or "查询报告\n\n一、查询结论\n本次查询未返回可展示的表格字段。\n\n二、结果说明\n请检查 SQL 是否成功执行。"
        )
    if not rows:
        return (
            "查询报告\n\n"
            "一、查询结论\n"
            "暂未检索到符合条件的记录。\n\n"
            "二、结果说明\n"
            "建议调整时间、地区、编号或异常类型等筛选条件后重新查询。"
        )

    sample_rows = rows[:20]
    payload = {
        "question": question,
        "columns": columns,
        "row_count": total_rows,
        "rows": sample_rows,
    }
    if mode == "result_analysis":
        prompt = (
            "你是高切坡业务系统的结果分析器。"
            "你只能依据下面给出的结果表进行分析，不能补充、猜测或编造表格中没有的数据。\n"
            "当前用户的问题属于分析型问题，请输出一份中文“查询报告”，必须严格使用下面结构：\n"
            "查询报告\n"
            "一、查询结论\n"
            "二、关键发现\n"
            "三、结果说明\n\n"
            "写作要求：\n"
            "1. 在“查询结论”中直接回答用户想看的分析结论，并明确本次共返回多少条记录；\n"
            "2. 在“关键发现”中用 2 到 4 条短句提炼地区、时间、状态、异常类型、数量分布或排序变化；\n"
            "3. 在“结果说明”中提示完整明细见结果表格；\n"
            "4. 不要输出查询语句，不要描述系统内部执行过程，不要编造没有证据的原因或处置建议。\n\n"
            f"结果表 JSON：\n{json.dumps(payload, ensure_ascii=False, default=str)}"
        )
    else:
        prompt = (
            "你是高切坡业务系统的结果分析器。"
            "你只能依据下面给出的结果表进行分析，不能补充、猜测或编造表格中没有的数据。\n"
            "请输出一份中文“查询报告”，必须严格使用下面结构：\n"
            "查询报告\n"
            "一、查询结论\n"
            "二、关键发现\n"
            "三、结果说明\n\n"
            "写作要求：\n"
            "1. 在“查询结论”中直接回答用户问题，并明确本次共返回多少条记录；\n"
            "2. 在“关键发现”中提炼表格中的关键状态、异常类型、时间、地区或统计特征；\n"
            "3. 如果结果较多，只概括代表性信息；\n"
            "4. 在“结果说明”中提示完整明细见结果表格；\n"
            "5. 不要输出查询语句，不要描述系统内部执行过程，不要编造处置建议。\n\n"
            f"结果表 JSON：\n{json.dumps(payload, ensure_ascii=False, default=str)}"
        )

    try:
        response = llm.invoke(prompt)
        content = getattr(response, "content", response)
        return str(content).strip() or fallback
    except Exception:
        return fallback or build_cached_summary(rows, total_rows)


def clean_logs(logs: str) -> str:
    """清洗 Agent 日志，隐藏表结构 DDL，避免用户误认为系统执行了 CREATE TABLE。"""
    logs = ANSI_RE.sub("", logs)
    return SCHEMA_DDL_RE.sub("[表结构详情已隐藏，仅用于 Agent 理解字段，不是执行建表语句]", logs)


def _compact_text(value, max_len: int = 1200) -> str:
    text_value = clean_logs(str(value))
    return text_value if len(text_value) <= max_len else text_value[:max_len] + "\n..."


def _extract_sql_from_value(value) -> str:
    """从 LangChain tool_input 的不同结构中提取 SQL 字符串。"""
    if isinstance(value, dict):
        value = value.get("query") or value.get("sql") or value.get("input") or value
    return extract_sql_from_logs(f"Action Input: {json.dumps(str(value), ensure_ascii=False)}")


class AgentProgressHandler(BaseCallbackHandler):
    """把 Agent 工具调用转换成前端可展示的流式事件。"""

    def __init__(self, emit, state: dict):
        self.emit = emit
        self.state = state

    def on_agent_action(self, action, **kwargs):
        """Agent 准备调用工具时触发，用于推送进度和记录即将执行的数据查询。"""
        tool = getattr(action, "tool", "")
        tool_input = getattr(action, "tool_input", "")
        message = f"调用工具：{tool}"
        if tool == "sql_db_list_tables":
            message = "读取高切坡业务表列表"
        elif tool == "sql_db_schema":
            message = "核对业务数据字段"
        elif tool == "sql_db_query_checker":
            message = "校验数据口径"
        elif tool == "sql_db_query":
            message = "执行数据库查询"

        self.emit({
            "type": "progress",
            "message": message,
            "detail": _compact_text(tool_input, 600),
        })

        sql = _extract_sql_from_value(tool_input)
        if sql:
            self.state["last_sql"] = sql
            if tool == "sql_db_query":
                # 表格结果必须来自真实查询工具，不使用 Final Answer 文本解析。
                self.state["pending_query_sql"] = sql
                self.state["last_query_sql"] = sql
            # SQL is kept internally for result retrieval, but not streamed to the UI.

    def on_tool_end(self, output, **kwargs):
        """工具返回后触发；成功的数据查询会成为表格回查的首选口径。"""
        pending_query_sql = self.state.pop("pending_query_sql", "")
        if pending_query_sql and not str(output).lstrip().startswith("Error:"):
            self.state["last_success_query_sql"] = pending_query_sql

        self.emit({
            "type": "progress",
            "message": "工具返回结果",
            "detail": _compact_text(output, 900),
        })

    def on_agent_finish(self, finish, **kwargs):
        output = getattr(finish, "return_values", {}).get("output", "")
        if output:
            self.emit({
                "type": "progress",
                "message": "已完成业务数据检索",
                "detail": _compact_text(output, 700),
            })


def run_agent(question: str, progress=None, history: list[dict] | None = None) -> dict:
    """执行一次完整查询，并返回 SQL、表格数据、总结和日志。"""
    # progress 是给 SSE 用的回调；run_agent 本身仍然保持同步返回，方便网页和 App 共用。
    def emit(payload: dict):
        if progress:
            if payload.get("type") == "summary" and payload.get("summary"):
                payload = dict(payload)
                payload["summary"] = scrub_user_facing_text(str(payload["summary"]))
            if payload.get("type") == "progress":
                payload = dict(payload)
                payload.pop("detail", None)
                payload["message"] = scrub_user_facing_text(str(payload.get("message") or "正在处理业务数据"))
            progress(payload)

    print(">>> high-cut-slope SQL agent loaded")
    normalized_question = normalize_query_question(question)
    if normalized_question != question:
        print(f">>> [normalized_question] {question} -> {normalized_question}")
    conversation_history = normalize_history(history)
    route_llm_holder: dict[str, ChatOpenAI] = {}

    def get_route_llm() -> ChatOpenAI:
        route_llm = build_query_llm()
        route_llm_holder["llm"] = route_llm
        return route_llm

    route_decision = route_question(
        normalized_question,
        history=conversation_history,
        llm_factory=get_route_llm,
    )
    effective_question = resolve_effective_question(
        normalized_question,
        conversation_history,
        routed_question=route_decision.effective_question,
        use_history=route_decision.use_history,
    )
    if route_decision.use_history:
        print(">>> [conversation_context] router resolved current question with recent turns")
    print(
        ">>> [route] "
        f"status={route_decision.status} "
        f"query_type={route_decision.query_type} "
        f"route_name={route_decision.route_name or ''} "
        f"reason={route_decision.reason or ''} "
        f"use_history={route_decision.use_history}"
    )
    emit({"type": "progress", "message": "分析问题意图与业务范围"})

    if route_decision.status != "query":
        emit({
            "type": "summary",
            "summary": route_decision.summary,
            "message": "返回问题路由结果",
        })
        return build_non_query_result(question, route_decision)

    if has_photo_intent(effective_question):
        print(">>> [query_path] photo_sqlserver")
        emit({"type": "progress", "message": "连接现场照片库"})
        photo_payload = search_photo_records(effective_question)
        summary = build_photo_summary(question, photo_payload)
        emit({
            "type": "summary",
            "summary": summary,
            "message": "整理现场照片",
        })
        return {
            "status": "success",
            "query_type": route_decision.query_type,
            "question": question,
            "sql": photo_payload["sql"],
            "result": summary,
            "summary": summary,
            "report": None,
            "suggestion": None,
            "columns": photo_payload["columns"],
            "rows": photo_payload["rows"],
            "total_rows": photo_payload["total_rows"],
            "attachments": photo_payload["attachments"],
            "logs": "命中现场照片查询路径，直接从 SQL Server 照片库查询 tb_hcs_monitoring。",
            "error": None,
        }

    emit({"type": "progress", "message": "连接业务数据库"})

    if route_decision.query_type == "template_query":
        print(">>> [query_path] template_query")
        deterministic_query = get_deterministic_query(effective_question)
        if not deterministic_query:
            return {
                "status": "error",
                "query_type": "template_query",
                "question": question,
                "sql": "",
                "result": "",
                "summary": "",
                "report": None,
                "suggestion": "当前模板路由未找到对应查询实现，请检查业务模板配置。",
                "columns": [],
                "rows": [],
                "total_rows": 0,
                "logs": "模板路由命中，但未找到对应 deterministic query。",
                "error": "template_query implementation missing",
            }
        # 高频关键问题优先走稳定模板，避免让 LLM 在异常类型等关键口径上自由发挥。
        emit({
            "type": "progress",
            "message": "命中稳定业务查询模板",
            "detail": deterministic_query["summary"],
        })
        sql = deterministic_query["sql"]
        # Do not expose SQL to the user interface.
        query_source = deterministic_query.get("source", "dm")
        if query_source == "mixed":
            emit({
                "type": "progress",
                "message": "正在汇总达梦与 SQL Server 监测规模数据",
            })
            columns, rows, total_rows = get_county_monitoring_scale()
        elif query_source == "internal_report_inventory":
            inventory = get_report_asset_inventory()
            rows = [
                {
                    "区县": item.get("county", ""),
                    "月报份数": item.get("doc_count", 0),
                    "专业监测坡数量": item.get("professional_slope_count", 0),
                    "监测点数量": item.get("monitor_point_count", 0),
                    "XYH月度记录": item.get("xyh_record_count", 0),
                    "现场照片": item.get("photo_count", 0),
                    "稳定性评价": item.get("stability_count", 0),
                    "需现场复核": item.get("review_count", 0),
                }
                for item in inventory.get("counties", [])
            ]
            columns = ["区县", "月报份数", "专业监测坡数量", "监测点数量", "XYH月度记录", "现场照片", "稳定性评价", "需现场复核"]
            total_rows = len(rows)
        elif query_source == "sqlserver":
            try:
                emit({
                    "type": "progress",
                    "message": "正在从 SQL Server 源库读取群测群防数据",
                })
                columns, rows, total_rows = query_sqlserver_for_display(sql)
            except Exception as exc:
                print(f">>> [sqlserver_fallback] {exc}")
                emit({
                    "type": "progress",
                    "message": "源库暂不可用，已自动切换到本地业务库查询",
                })
                db = get_db(include_tables=deterministic_query["tables"])
                columns, rows, total_rows = query_table_for_display(db, sql)
        else:
            db = get_db(include_tables=deterministic_query["tables"])
            columns, rows, total_rows = query_table_for_display(db, sql)
        columns, rows = enrich_rows(deterministic_query["name"], columns, rows)
        attachments = enrich_photo_attachments(question, rows)
        emit({
            "type": "progress",
            "message": "基于查询结果生成业务分析",
        })
        template_summary = build_template_summary(
            deterministic_query["name"],
            deterministic_query["summary"],
            rows,
            total_rows,
            question,
        )
        if deterministic_query["name"] in {
            "county_overview",
            "recent_risk_county",
            "recent_slope_brief",
            "recent_large_displacement",
            "recent_monitoring_abnormal",
            "focus_slope_attention",
            "qmqf_review_list",
            "county_monitoring_scale",
            "report_asset_inventory",
            "personnel_info",
            "abnormal_type",
            "county_abnormal_compare",
        }:
            summary = template_summary
        else:
            summary = analyze_query_result(
                build_report_llm(),
                question,
                sql,
                columns,
                rows,
                total_rows,
                template_summary,
                mode="db_query",
            )
        summary = append_followup_guidance(
            summary,
            deterministic_query["name"],
            normalized_question,
        )
        emit({
            "type": "summary",
            "summary": summary,
            "message": "生成查询报告",
        })
        text_only_templates = {"county_overview", "recent_risk_county"}
        response_columns = [] if deterministic_query["name"] in text_only_templates else columns
        response_rows = [] if deterministic_query["name"] in text_only_templates else rows
        response_total_rows = 0 if deterministic_query["name"] in text_only_templates else total_rows
        return {
            "status": "success",
            "query_type": "template_query",
            "question": question,
            "sql": sql,
            "result": summary,
            "summary": summary,
            "report": None,
            "suggestion": None,
            "columns": response_columns,
            "rows": response_rows,
            "total_rows": response_total_rows,
            "attachments": attachments,
            "logs": "命中稳定业务查询模板，未重新调用 Agent 生成 SQL。",
            "error": None,
        }

    include_tables = select_include_tables(effective_question)
    table_guide = build_schema_guide(effective_question)
    emit({
        "type": "progress",
        "message": "检索真实数据库 schema 知识",
        "detail": "候选表：" + ", ".join(include_tables),
    })

    db = get_db(include_tables=include_tables)
    emit({"type": "progress", "message": "正在组织业务查询"})

    if not QUERY_API_KEY:
        summary = user_friendly_error_message("Missing credentials")
        return {
            "status": "clarify",
            "query_type": route_decision.query_type,
            "question": question,
            "sql": "",
            "result": summary,
            "summary": summary,
            "report": None,
            "suggestion": None,
            "columns": [],
            "rows": [],
            "total_rows": 0,
            "logs": "",
            "error": None,
        }

    # 结果分析型问题更依赖“这次问题的聚合口径”，缓存很容易把历史错误 SQL 放大。
    # 因此当前只对普通事实查询复用 SQL 缓存，分析类问题每次重新确定查询口径。
    cached_sql = (
        get_cached_sql(normalized_question)
        if route_decision.query_type == "db_query" and not route_decision.use_history
        else ""
    )
    if cached_sql:
        print(">>> [query_path] cached_sql")
        # 这里缓存的是“查询口径”而不是结果本身：同一句问题复用已验证 SQL，
        # 但仍然实时查库，保证数据是新的。
        emit({
            "type": "progress",
            "message": "正在整理已验证的业务结果",
            "detail": cached_sql,
        })
        # Do not expose SQL to the user interface.
        columns, rows, total_rows = query_table_for_display(db, cached_sql)
        attachments = enrich_photo_attachments(question, rows)
        emit({
            "type": "progress",
            "message": "基于缓存 SQL 的查询结果生成业务分析",
        })
        summary = analyze_query_result(
            build_report_llm(),
            question,
            cached_sql,
            columns,
            rows,
            total_rows,
            build_cached_summary(rows, total_rows),
            mode=route_decision.query_type,
        )
        summary = append_followup_guidance(
            summary,
            route_decision.route_name or route_decision.query_type,
            normalized_question,
        )
        emit({
            "type": "summary",
            "summary": summary,
            "message": "生成查询报告",
        })
        return {
            "status": "success",
            "query_type": route_decision.query_type,
            "question": question,
            "sql": cached_sql,
            "result": summary,
            "summary": summary,
            "report": None,
            "suggestion": None,
            "columns": columns,
            "rows": rows,
            "total_rows": total_rows,
            "attachments": attachments,
            "logs": "命中已验证 SQL 缓存，未重新调用 Agent 生成 SQL。",
            "error": None,
        }

    query_llm = route_llm_holder.get("llm") or build_query_llm()
    print(">>> [query_path] agent_sql")
    state: dict[str, str] = {}
    callbacks = [AgentProgressHandler(emit, state)]

    agent = create_sql_agent(
        llm=query_llm,
        db=db,
        prefix=GQP_AGENT_PREFIX.format(
            dialect="{dialect}",
            top_k="{top_k}",
            table_guide=table_guide,
        ),
        top_k=2000,
        max_iterations=8,
        verbose=True,
        handle_parsing_errors=True,
        agent_executor_kwargs={
            "handle_parsing_errors": True,
            "callbacks": callbacks,
        },
    )

    log_buffer = io.StringIO()

    try:
        with redirect_stdout(log_buffer):
            result = agent.invoke({"input": effective_question}, config={"callbacks": callbacks})

        logs = log_buffer.getvalue()
        # 表格数据必须追溯到最后一次真正成功执行的 sql_db_query。
        # 不能只拿 checker 或模型自述里的 SQL，否则前端表格和真实结果会对不上。
        sql = (
            state.get("last_success_query_sql")
            or state.get("last_query_sql")
            or state.get("last_sql")
            or extract_sql_from_logs(logs)
        )
        agent_output = result.get("output", "")
        summary = ""
        columns = []
        rows = []
        total_rows = 0
        error = None

        if sql and FORBIDDEN_SQL_RE.search(sql):
            summary = ""
            error = "已拦截非只读 SQL，高切坡智能查询仅允许 SELECT/WITH 查询。"
        else:
            emit({
                "type": "progress",
                "message": "整理数据库查询表格",
                "detail": sql,
            })
            # 最终再次回查数据库，把 SQL 结果转成 columns/rows，作为前端表格唯一数据源。
            columns, rows, total_rows = query_table_for_display(db, sql)
            attachments = enrich_photo_attachments(question, rows)
            emit({
                "type": "progress",
                "message": f"业务明细已整理完成：共 {total_rows} 条，本页 {len(rows)} 条",
            })
            if sql and not route_decision.use_history:
                save_cached_sql(normalized_question, sql)
            emit({
                "type": "progress",
                "message": "基于查询结果生成业务分析",
            })
            # 这一步的 LLM 只负责“读表总结”，不再决定查什么表、怎么写 SQL。
            summary = analyze_query_result(
                build_report_llm(),
                question,
                sql,
                columns,
                rows,
                total_rows,
                agent_output,
                mode=route_decision.query_type,
            )
            summary = append_followup_guidance(
                summary,
                route_decision.route_name or route_decision.query_type,
                normalized_question,
            )
            emit({
                "type": "summary",
                "summary": summary,
                "message": "生成查询报告",
            })

        return {
            "status": "success",
            "query_type": route_decision.query_type,
            "question": question,
            "sql": sql,
            "result": summary,
            "summary": summary,
            "report": None,
            "suggestion": None,
            "columns": columns,
            "rows": rows,
            "total_rows": total_rows,
            "attachments": attachments if "attachments" in locals() else [],
            "logs": clean_logs(logs),
            "error": error,
        }
    except Exception as e:
        logs = log_buffer.getvalue()
        error = str(e)
        sql = (
            state.get("last_success_query_sql")
            or state.get("last_query_sql")
            or state.get("last_sql")
            or extract_sql_from_logs(logs)
        )
        recovered_answer = extract_answer_from_parsing_error(error)
        # LangChain 偶尔会在“已经查到数据并生成答案”后，因为输出格式不标准而抛解析异常。
        # 这里尽量从日志和异常里恢复 SQL 与中文答案，避免用户白等一轮却什么都拿不到。
        columns, rows, total_rows = query_table_for_display(db, sql)
        attachments = enrich_photo_attachments(question, rows)
        summary = analyze_query_result(
            build_report_llm(),
            question,
            sql,
            columns,
            rows,
            total_rows,
            recovered_answer,
            mode=route_decision.query_type,
        )
        summary = append_followup_guidance(
            summary,
            route_decision.route_name or route_decision.query_type,
            normalize_query_question(question),
        )
        return {
            "status": "success" if summary else "error",
            "query_type": route_decision.query_type,
            "question": question,
            "sql": sql,
            "result": summary,
            "summary": summary,
            "report": None,
            "suggestion": None,
            "columns": columns,
            "rows": rows,
            "total_rows": total_rows,
            "attachments": attachments,
            "logs": clean_logs(logs),
            "error": None if summary else error,
        }


def stream_agent_events(question: str):
    """把同步 Agent 调用包装成 SSE 事件流，供前端实时展示思考过程。"""
    event_queue = queue.Queue()

    def emit(payload: dict):
        event_queue.put(payload)

    def worker():
        try:
            result = run_agent(question, progress=emit)
            event_queue.put({"type": "final", "data": sanitize_query_result(result)})
        except Exception as exc:
            event_queue.put({"type": "error", "message": user_friendly_error_message(exc)})
        finally:
            event_queue.put(STREAM_DONE)

    # Agent 查询可能持续几秒到几十秒，单独起线程避免阻塞 SSE 生成器本身。
    threading.Thread(target=worker, daemon=True).start()

    while True:
        event = event_queue.get()
        if event is STREAM_DONE:
            break
        yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
