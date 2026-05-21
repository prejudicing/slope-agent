"""高切坡智能查询 Agent 主流程。

本模块负责把用户自然语言问题交给 LangChain SQL Agent，实时推送思考过程，
并把最后一次成功执行的 SQL 结果重新整理成前端可展示的表格。
"""

import io
import json
import queue
import re
import threading
from contextlib import redirect_stdout

from sqlalchemy import text
from langchain_openai import ChatOpenAI
from langchain_community.agent_toolkits import create_sql_agent

try:
    from langchain_core.callbacks import BaseCallbackHandler
except Exception:
    BaseCallbackHandler = object

from app.db import get_db
from app.business_queries import enrich_rows, get_deterministic_query
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
)
from app.conversation_context import (
    build_effective_question,
    normalize_history,
)
from app.domain import GQP_AGENT_PREFIX
from app.query_cache import get_cached_sql, save_cached_sql
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
STREAM_DONE = object()
DISPLAY_ROW_LIMIT = 200


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
    return {
        "status": decision.status,
        "query_type": decision.query_type,
        "question": question,
        "sql": "",
        "result": decision.summary,
        "summary": decision.summary,
        "report": None,
        "suggestion": decision.suggestion,
        "columns": [],
        "rows": [],
        "total_rows": 0,
        "logs": f"问题路由结果：{decision.reason}",
        "error": None,
    }


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
            "查询报告\n\n"
            "一、查询结论\n"
            f"本次复用已验证查询口径，查询到 {total_rows} 条记录。\n\n"
            "二、结果说明\n"
            f"当前页面展示前 {len(rows)} 条样本，详细记录请查看下方查询结果表格。"
        )
    return (
        "查询报告\n\n"
        "一、查询结论\n"
        "本次复用已验证查询口径，但数据库未返回匹配记录。\n\n"
        "二、结果说明\n"
        "建议调整筛选条件后重新查询。"
    )


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


def build_report_llm() -> ChatOpenAI:
    """报告阶段模型：允许开启 thinking，但限制在 high 级别。"""
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
    llm: ChatOpenAI,
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
    if not columns:
        return (
            fallback
            or "查询报告\n\n一、查询结论\n本次查询未返回可展示的表格字段。\n\n二、结果说明\n请检查 SQL 是否成功执行。"
        )
    if not rows:
        return (
            "查询报告\n\n"
            "一、查询结论\n"
            "本次查询已执行，但数据库没有返回匹配记录。\n\n"
            "二、结果说明\n"
            "建议调整时间、地区、编号或异常类型等筛选条件后重新查询。"
        )

    sample_rows = rows[:20]
    payload = {
        "question": question,
        "sql": sql,
        "columns": columns,
        "row_count": total_rows,
        "rows": sample_rows,
    }
    if mode == "result_analysis":
        prompt = (
            "你是高切坡系统智能查询 Agent 的结果分析器。"
            "你只能依据下面给出的真实 SQL 查询结果表进行分析，不能补充、猜测或编造表格中没有的数据。\n"
            "当前用户的问题属于分析型问题，请输出一份中文“查询报告”，必须严格使用下面结构：\n"
            "查询报告\n"
            "一、查询结论\n"
            "二、关键发现\n"
            "三、结果说明\n\n"
            "写作要求：\n"
            "1. 在“查询结论”中直接回答用户想看的分析结论，并明确本次共返回多少条记录；\n"
            "2. 在“关键发现”中用 2 到 4 条短句提炼地区、时间、状态、异常类型、数量分布或排序变化；\n"
            "3. 在“结果说明”中提示完整明细见结果表格；\n"
            "4. 不要输出 SQL，不要说“我查询了数据库”，不要编造没有证据的原因或处置建议。\n\n"
            f"真实查询结果 JSON：\n{json.dumps(payload, ensure_ascii=False, default=str)}"
        )
    else:
        prompt = (
            "你是高切坡系统智能查询 Agent 的结果分析器。"
            "你只能依据下面给出的真实 SQL 查询结果表进行分析，不能补充、猜测或编造表格中没有的数据。\n"
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
            "5. 不要输出 SQL，不要说“我查询了数据库”，不要编造处置建议。\n\n"
            f"真实查询结果 JSON：\n{json.dumps(payload, ensure_ascii=False, default=str)}"
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
        """Agent 准备调用工具时触发，用于推送进度和记录即将执行的 SQL。"""
        tool = getattr(action, "tool", "")
        tool_input = getattr(action, "tool_input", "")
        message = f"调用工具：{tool}"
        if tool == "sql_db_list_tables":
            message = "读取高切坡业务表列表"
        elif tool == "sql_db_schema":
            message = f"查看表结构：{tool_input}"
        elif tool == "sql_db_query_checker":
            message = "校验生成的 SQL"
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
            self.emit({"type": "sql", "sql": sql})

    def on_tool_end(self, output, **kwargs):
        """工具返回后触发；成功的 sql_db_query 会成为表格回查的首选 SQL。"""
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
                "message": "SQL Agent 已完成查询阶段",
                "detail": _compact_text(output, 700),
            })


def run_agent(question: str, progress=None, history: list[dict] | None = None) -> dict:
    """执行一次完整查询，并返回 SQL、表格数据、总结和日志。"""
    # progress 是给 SSE 用的回调；run_agent 本身仍然保持同步返回，方便网页和 App 共用。
    def emit(payload: dict):
        if progress:
            progress(payload)

    print(">>> high-cut-slope SQL agent loaded")
    conversation_history = normalize_history(history)
    normalized_question = normalize_query_question(question)
    if normalized_question != question:
        print(f">>> [normalized_question] {question} -> {normalized_question}")
    route_decision = route_question(normalized_question)
    effective_question = build_effective_question(normalized_question, conversation_history)

    # 当前问题本身如果已经是系统外问题，优先按新问题拒答，避免被旧上下文硬拉回高切坡业务。
    # 但如果当前问题只是条件不足，则允许模型结合最近几轮上下文自行判断能否补全成可查询问题。
    if route_decision.status == "clarify" and conversation_history:
        candidate_route = route_question(effective_question)
        if candidate_route.status == "query":
            route_decision = candidate_route
            print(">>> [conversation_context] using recent turns to resolve contextual query")
    print(
        ">>> [route] "
        f"status={route_decision.status} "
        f"query_type={route_decision.query_type} "
        f"route_name={route_decision.route_name or ''} "
        f"reason={route_decision.reason or ''}"
    )
    emit({"type": "progress", "message": "分析问题意图与业务范围"})

    if route_decision.status != "query":
        emit({
            "type": "summary",
            "summary": route_decision.summary,
            "message": "返回问题路由结果",
        })
        return build_non_query_result(question, route_decision)

    emit({"type": "progress", "message": "连接达梦数据库"})

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
        db = get_db(include_tables=deterministic_query["tables"])
        sql = deterministic_query["sql"]
        emit({"type": "sql", "sql": sql})
        columns, rows, total_rows = query_table_for_display(db, sql)
        columns, rows = enrich_rows(deterministic_query["name"], columns, rows)
        emit({
            "type": "progress",
            "message": "基于查询结果生成业务分析",
        })
        summary = analyze_query_result(
            build_report_llm(),
            question,
            sql,
            columns,
            rows,
            total_rows,
            (
                f"{deterministic_query['summary']} 本次查询到 {total_rows} 条异常记录，"
                f"当前页面展示前 {len(rows)} 条样本，异常类型已在结果表格的 abnormal_type 字段中列出。"
            ),
            mode="db_query",
        )
        emit({
            "type": "summary",
            "summary": summary,
            "message": "生成查询报告",
        })
        return {
            "status": "success",
            "query_type": "template_query",
            "question": question,
            "sql": sql,
            "result": summary,
            "summary": summary,
            "report": None,
            "suggestion": None,
            "columns": columns,
            "rows": rows,
            "total_rows": total_rows,
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
    emit({"type": "progress", "message": "初始化高切坡业务 Agent"})

    # 结果分析型问题更依赖“这次问题的聚合口径”，缓存很容易把历史错误 SQL 放大。
    # 因此当前只对普通事实查询复用 SQL 缓存，分析类问题每次重新确定查询口径。
    cached_sql = (
        get_cached_sql(normalized_question)
        if route_decision.query_type == "db_query" and not conversation_history
        else ""
    )
    if cached_sql:
        print(">>> [query_path] cached_sql")
        # 这里缓存的是“查询口径”而不是结果本身：同一句问题复用已验证 SQL，
        # 但仍然实时查库，保证数据是新的。
        emit({
            "type": "progress",
            "message": "命中已验证 SQL，复用稳定查询口径",
            "detail": cached_sql,
        })
        emit({"type": "sql", "sql": cached_sql})
        columns, rows, total_rows = query_table_for_display(db, cached_sql)
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
            "logs": "命中已验证 SQL 缓存，未重新调用 Agent 生成 SQL。",
            "error": None,
        }

    query_llm = build_query_llm()
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
            emit({
                "type": "progress",
                "message": f"查询结果已同步到表格：总计 {total_rows} 条，当前展示 {len(rows)} 条",
            })
            if sql and not conversation_history:
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
            "logs": clean_logs(logs),
            "error": None if summary else error,
        }


def stream_agent_events(question: str, history: list[dict] | None = None):
    """把同步 Agent 调用包装成 SSE 事件流，供前端实时展示思考过程。"""
    event_queue = queue.Queue()

    def emit(payload: dict):
        event_queue.put(payload)

    def worker():
        try:
            result = run_agent(question, progress=emit, history=history)
            event_queue.put({"type": "final", "data": result})
        except Exception as exc:
            event_queue.put({"type": "error", "message": str(exc)})
        finally:
            event_queue.put(STREAM_DONE)

    # Agent 查询可能持续几秒到几十秒，单独起线程避免阻塞 SSE 生成器本身。
    threading.Thread(target=worker, daemon=True).start()

    while True:
        event = event_queue.get()
        if event is STREAM_DONE:
            break
        yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
