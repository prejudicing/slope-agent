"""HTTP API 层。

提供普通查询接口、流式查询接口，以及移动端录音转文字接口。
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from app.agent import run_agent, sanitize_query_result, stream_agent_events, user_friendly_error_message
from app.asr import AsrError, transcribe_base64_audio
from app.displacement_dashboard import get_recent_displacement_dashboard
from app.photo_cache import get_cached_photo_response
from app.photo_service import download_photo_file
from app.qmqf_dashboard import get_qmqf_abnormal_dashboard
from app.report_assets import get_recent_report_stability_assets
from app.report_inventory import get_report_asset_inventory
from app.text_normalizer import normalize_query_text

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
        result = run_agent(normalize_query_text(req.question))
        return sanitize_query_result(result)
    except Exception as e:
        message = user_friendly_error_message(e)
        # 非流式接口也保持和前端约定一致的返回结构，避免调用方额外分支判断。
        return {
            "status": "clarify",
            "query_type": "error",
            "question": req.question,
            "sql": "",
            "result": message,
            "summary": message,
            "report": None,
            "suggestion": None,
            "columns": [],
            "rows": [],
            "total_rows": 0,
            "attachments": [],
            "logs": "",
            "error": None,
        }


@router.get("/report/asset-inventory")
def report_asset_inventory():
    """读取月报内容资产清单。"""
    try:
        return get_report_asset_inventory()
    except Exception as e:
        return {
            "status": "error",
            "title": "月报内容资产清单",
            "description": "",
            "summary": {},
            "counties": [],
            "error": str(e),
        }


@router.post("/query/stream")
def query_stream(req: QueryRequest):
    """流式查询接口，使用 SSE 持续返回 Agent 进度、SQL、总结和最终表格数据。"""
    return StreamingResponse(
        stream_agent_events(normalize_query_text(req.question)),
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
        text = normalize_query_text(text)
        return {"text": text, "error": None}
    except AsrError as e:
        # AsrError 属于“用户可理解”的业务错误，直接返回给前端做友好提示。
        return {"text": "", "error": str(e)}
    except Exception as e:
        return {"text": "", "error": f"语音转写失败：{e}"}


@router.get("/displacement/recent-large")
def recent_large_displacement():
    """?????????????????????????"""
    try:
        return get_recent_displacement_dashboard()
    except Exception as e:
        return {
            "status": "error",
            "title": "?????????????????",
            "description": "",
            "items": [],
            "error": str(e),
        }


@router.get("/qmqf/abnormal-dashboard")
def qmqf_abnormal_dashboard():
    """??/??????????????????????"""
    try:
        return get_qmqf_abnormal_dashboard()
    except Exception as e:
        return {
            "status": "error",
            "title": "??????????????",
            "description": "",
            "items": [],
            "error": str(e),
        }


@router.get("/photo-cache")
def photo_cache(path: str, size: str = "thumb"):
    """缓存并压缩远程现场照片，减少手机端原图加载卡顿。"""
    return get_cached_photo_response(path=path, size=size)


@router.get("/report/stability-assets")
def report_stability_assets(limit: int = 12, county: str = "", gqpbh: str = "", only_with_photos: bool = False):
    """读取月报稳定性评价和关联照片资产。"""
    try:
        return get_recent_report_stability_assets(
            limit=limit,
            county=county,
            gqpbh=gqpbh,
            only_with_photos=only_with_photos,
        )
    except Exception:
        return {
            "status": "error",
            "title": "近期月报稳定性评价与现场照片",
            "description": "",
            "items": [],
            "error": "月报稳定性评价资产读取失败",
        }


@router.get("/photo/file")
def photo_file(path: str = Query(..., min_length=1)):
    """代理下载现场照片/视频，避免前端直接依赖文件服务器地址。"""
    try:
        content, content_type = download_photo_file(path)
        return Response(content=content, media_type=content_type)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
