"""HTTP API 层。

提供普通查询接口、流式查询接口，以及移动端录音转文字接口。
"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent import run_agent, stream_agent_events
from app.asr import AsrError, transcribe_base64_audio

router = APIRouter()


class QueryRequest(BaseModel):
    """前端提交的自然语言查询问题。"""

    question: str


class AsrRequest(BaseModel):
    """移动端录音上传后的转写请求。"""

    audio_base64: str
    mime_type: str
    filename: str | None = None


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


@router.post("/asr")
def asr(req: AsrRequest):
    """把移动端上传的录音转成中文文本。"""
    try:
        text = transcribe_base64_audio(
            audio_base64=req.audio_base64,
            mime_type=req.mime_type,
            filename=req.filename,
        )
        return {"text": text, "error": None}
    except AsrError as e:
        return {"text": "", "error": str(e)}
    except Exception as e:
        return {"text": "", "error": f"语音转写失败：{e}"}
