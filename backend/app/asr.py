"""本地语音转文字能力。

移动端 App 把录音 base64 和 mimeType 发到后端，后端使用本地 faster-whisper
模型执行中文语音转写，不依赖外部 ASR API。
"""

from __future__ import annotations

import base64
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Optional

from faster_whisper import WhisperModel

from app.config import ASR_COMPUTE_TYPE, ASR_DEVICE, ASR_MODEL


class AsrError(RuntimeError):
    """语音转写业务错误，供 API 层转换成友好的返回。"""


DATA_URL_RE = re.compile(r"^data:[^;]+;base64,", re.IGNORECASE)
_MODEL_LOCK = threading.Lock()
_MODEL_INSTANCE: WhisperModel | None = None


def _guess_suffix(mime_type: str, filename: Optional[str]) -> str:
    if filename:
        suffix = Path(filename).suffix
        if suffix:
            return suffix

    suffix_map = {
        "audio/aac": ".aac",
        "audio/mp4": ".m4a",
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
    }
    return suffix_map.get(mime_type.split(";")[0].strip().lower(), ".m4a")


def _decode_audio_base64(audio_base64: str) -> bytes:
    """兼容原生插件返回的 base64 变体。"""
    normalized = audio_base64.strip()
    normalized = DATA_URL_RE.sub("", normalized)
    normalized = re.sub(r"\s+", "", normalized)

    if not normalized:
        raise AsrError("录音内容为空。")

    padding = len(normalized) % 4
    if padding:
        normalized += "=" * (4 - padding)

    try:
        return base64.b64decode(normalized, validate=False)
    except Exception as exc:
        raise AsrError("录音数据格式无效，无法解码。") from exc


def _get_model() -> WhisperModel:
    """懒加载本地 ASR 模型，避免应用启动即占用较长初始化时间。"""
    global _MODEL_INSTANCE
    if _MODEL_INSTANCE is not None:
        return _MODEL_INSTANCE

    with _MODEL_LOCK:
        if _MODEL_INSTANCE is None:
            try:
                _MODEL_INSTANCE = WhisperModel(
                    ASR_MODEL,
                    device=ASR_DEVICE,
                    compute_type=ASR_COMPUTE_TYPE,
                )
            except Exception as exc:
                raise AsrError(
                    "本地 ASR 模型加载失败。"
                    f" 当前配置为 model={ASR_MODEL}, device={ASR_DEVICE}, compute_type={ASR_COMPUTE_TYPE}。"
                    " 如果是首次启动，请确认服务器可以下载模型，或者把 ASR_MODEL 指向本地模型目录。"
                ) from exc
    return _MODEL_INSTANCE


def transcribe_base64_audio(audio_base64: str, mime_type: str, filename: Optional[str] = None) -> str:
    """把前端上传的 base64 音频转成本地识别文本。"""
    if not audio_base64:
        raise AsrError("录音内容为空。")

    audio_bytes = _decode_audio_base64(audio_base64)
    if not audio_bytes:
        raise AsrError("录音内容为空。")

    suffix = _guess_suffix(mime_type or "", filename)
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            temp_path = tmp.name

        model = _get_model()
        segments, info = model.transcribe(
            temp_path,
            language="zh",
            vad_filter=True,
            condition_on_previous_text=False,
        )

        text = "".join(segment.text for segment in segments).strip()
        if not text:
            raise AsrError("本地语音转写未返回有效文本。")
        return text
    except AsrError:
        raise
    except Exception as exc:
        raise AsrError(f"本地语音转写失败：{exc}") from exc
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
