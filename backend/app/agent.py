import io
import re
from contextlib import redirect_stdout

from sqlalchemy import text
from langchain_openai import ChatOpenAI
from langchain_community.agent_toolkits import create_sql_agent

from app.db import get_db
from app.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from app.domain import GQP_AGENT_PREFIX, GQP_TABLE_GUIDE


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


def extract_sql_from_logs(log_text: str) -> str:
    patterns = [
        r'Action Input:\s*"((?:SELECT|WITH).*?)"',
        r'Action Input:\s*```sql\s*(.*?)\s*```',
        r'```sql\s*(.*?)\s*```',
    ]

    matches = []
    for pattern in patterns:
        found = re.findall(pattern, log_text, flags=re.IGNORECASE | re.DOTALL)
        if found:
            matches.extend(found)

    if not matches:
        return ""

    sql = matches[-1].strip()
    sql = sql.replace('\\"', '"').replace("\\n", "\n")
    return sql


def extract_answer_from_parsing_error(error_text: str) -> str:
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
    logs = ANSI_RE.sub("", logs)
    return SCHEMA_DDL_RE.sub("[表结构详情已隐藏，仅用于 Agent 理解字段，不是执行建表语句]", logs)


def run_agent(question: str) -> dict:
    print(">>> high-cut-slope SQL agent loaded")

    db = get_db()

    llm_kwargs = {
        "model": OPENAI_MODEL,
        "temperature": 0,
        "api_key": OPENAI_API_KEY,
    }
    if OPENAI_BASE_URL:
        llm_kwargs["base_url"] = OPENAI_BASE_URL

    llm = ChatOpenAI(**llm_kwargs)

    agent = create_sql_agent(
        llm=llm,
        db=db,
        prefix=GQP_AGENT_PREFIX.format(
            dialect="{dialect}",
            top_k="{top_k}",
            table_guide=GQP_TABLE_GUIDE,
        ),
        top_k=20,
        max_iterations=8,
        verbose=True,
        handle_parsing_errors=True,
        agent_executor_kwargs={"handle_parsing_errors": True},
    )

    log_buffer = io.StringIO()

    try:
        with redirect_stdout(log_buffer):
            result = agent.invoke({"input": question})

        logs = log_buffer.getvalue()
        sql = extract_sql_from_logs(logs)
        summary = result.get("output", "")
        columns = []
        rows = []
        error = None

        if sql and FORBIDDEN_SQL_RE.search(sql):
            summary = ""
            error = "已拦截非只读 SQL，高切坡智能查询仅允许 SELECT/WITH 查询。"
        else:
            columns, rows = query_table_for_display(db, sql)

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
        sql = extract_sql_from_logs(logs)
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
