"""HTTP API 层。

提供普通查询接口和流式查询接口；前端主要使用 `/query/stream` 展示实时思考过程。
"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent import run_agent, stream_agent_events

router = APIRouter()


class QueryRequest(BaseModel):
    """前端提交的自然语言查询问题。"""

    question: str


@router.get("/health")
def health():
    """健康检查接口，便于确认后端服务是否可访问。"""
    return {"status": "ok"}


@router.post("/query")
def query(req: QueryRequest):
    """非流式查询接口，保留给调试或简单调用场景。"""
    try:
        result = run_agent(req.question)
        return result
    except Exception as e:
        return {
            "question": req.question,
            "sql": "",
            "result": "",
            "summary": "",
            "columns": [],
            "rows": [],
            "logs": "",
            "error": str(e),
        }


@router.post("/query/stream")
def query_stream(req: QueryRequest):
    """流式查询接口，使用 SSE 持续返回 Agent 进度、SQL、总结和最终表格数据。"""
    return StreamingResponse(
        stream_agent_events(req.question),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
