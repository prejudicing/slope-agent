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
from app.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from app.domain import GQP_AGENT_PREFIX
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


def query_table_for_display(db, sql: str) -> tuple[list[str], list[dict]]:
    """用最终 SQL 重新查询一次数据库，生成前端 ResultPanel 需要的 columns/rows。"""
    sql = normalize_sql(sql)
    if not sql or FORBIDDEN_SQL_RE.search(sql):
        return [], []

    engine = getattr(db, "_engine", None)
    if engine is None:
        return [], []

    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            columns = list(result.keys())
            rows = [
                {column: _serialize_cell(row[column]) for column in columns}
                for row in result.mappings().all()
            ]
        return columns, rows
    except Exception:
        return [], []


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
                "type": "summary",
                "summary": output,
                "message": "生成查询总结",
            })


def run_agent(question: str, progress=None) -> dict:
    """执行一次完整查询，并返回 SQL、表格数据、总结和日志。"""
    def emit(payload: dict):
        if progress:
            progress(payload)

    print(">>> high-cut-slope SQL agent loaded")
    emit({"type": "progress", "message": "连接达梦数据库"})

    include_tables = select_include_tables(question)
    table_guide = build_schema_guide(question)
    emit({
        "type": "progress",
        "message": "检索真实数据库 schema 知识",
        "detail": "候选表：" + ", ".join(include_tables),
    })

    db = get_db(include_tables=include_tables)
    emit({"type": "progress", "message": "初始化高切坡业务 Agent"})

    llm_kwargs = {
        "model": OPENAI_MODEL,
        "temperature": 0,
        "api_key": OPENAI_API_KEY,
    }
    if OPENAI_BASE_URL:
        llm_kwargs["base_url"] = OPENAI_BASE_URL

    llm = ChatOpenAI(**llm_kwargs)
    state: dict[str, str] = {}
    callbacks = [AgentProgressHandler(emit, state)]

    agent = create_sql_agent(
        llm=llm,
        db=db,
        prefix=GQP_AGENT_PREFIX.format(
            dialect="{dialect}",
            top_k="{top_k}",
            table_guide=table_guide,
        ),
        top_k=20,
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
            result = agent.invoke({"input": question}, config={"callbacks": callbacks})

        logs = log_buffer.getvalue()
        # 优先使用最后一次成功执行的 sql_db_query，避免 checker 或日志摘要污染结果表格。
        sql = (
            state.get("last_success_query_sql")
            or state.get("last_query_sql")
            or state.get("last_sql")
            or extract_sql_from_logs(logs)
        )
        summary = result.get("output", "")
        columns = []
        rows = []
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
            columns, rows = query_table_for_display(db, sql)
            emit({
                "type": "progress",
                "message": f"查询结果已同步到表格：{len(rows)} 条",
            })

        return {
            "question": question,
            "sql": sql,
            "result": summary,
            "summary": summary,
            "columns": columns,
            "rows": rows,
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
        columns, rows = query_table_for_display(db, sql)
        return {
            "question": question,
            "sql": sql,
            "result": recovered_answer,
            "summary": recovered_answer,
            "columns": columns,
            "rows": rows,
            "logs": clean_logs(logs),
            "error": None if recovered_answer else error,
        }


def stream_agent_events(question: str):
    """把同步 Agent 调用包装成 SSE 事件流，供前端实时展示思考过程。"""
    event_queue = queue.Queue()

    def emit(payload: dict):
        event_queue.put(payload)

    def worker():
        try:
            result = run_agent(question, progress=emit)
            event_queue.put({"type": "final", "data": result})
        except Exception as exc:
            event_queue.put({"type": "error", "message": str(exc)})
        finally:
            event_queue.put(STREAM_DONE)

    threading.Thread(target=worker, daemon=True).start()

    while True:
        event = event_queue.get()
        if event is STREAM_DONE:
            break
        yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
