from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent import run_agent, stream_agent_events

router = APIRouter()


class QueryRequest(BaseModel):
    question: str


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/query")
def query(req: QueryRequest):
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
    return StreamingResponse(
        stream_agent_events(req.question),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
