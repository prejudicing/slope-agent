from fastapi import APIRouter
from pydantic import BaseModel

from app.agent import run_agent

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
