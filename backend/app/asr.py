"""语音转文字能力。

当前实现面向移动端 App 的录音上传场景：前端把录音的 base64 和 mimeType
发送到后端，后端再调用 OpenAI 兼容的音频转写接口返回文本。
"""

from __future__ import annotations

import base64
import io
import re
from typing import Optional

from openai import OpenAI

from app.config import OPENAI_API_KEY, OPENAI_ASR_MODEL, OPENAI_BASE_URL


class AsrError(RuntimeError):
    """语音转写业务错误，供 API 层转换成友好的返回。"""


DATA_URL_RE = re.compile(r"^data:[^;]+;base64,", re.IGNORECASE)


def _build_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise AsrError("未配置 OPENAI_API_KEY，无法执行语音转写。")

    kwargs = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)


def _guess_filename(mime_type: str, filename: Optional[str]) -> str:
    if filename:
        return filename

    suffix_map = {
        "audio/aac": "aac",
        "audio/mp4": "m4a",
        "audio/mpeg": "mp3",
        "audio/wav": "wav",
        "audio/webm": "webm",
        "audio/ogg": "ogg",
    }
    suffix = suffix_map.get(mime_type.split(";")[0].strip().lower(), "m4a")
    return f"query_audio.{suffix}"


def _decode_audio_base64(audio_base64: str) -> bytes:
    """兼容原生插件返回的 base64 变体。

    Android 录音插件使用 Base64.DEFAULT，会带换行；有些端上实现还会返回
    data URL 前缀，因此这里统一做清洗后再解码。
    """
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


def transcribe_base64_audio(audio_base64: str, mime_type: str, filename: Optional[str] = None) -> str:
    """把前端上传的 base64 音频转成文本。"""
    if not audio_base64:
        raise AsrError("录音内容为空。")

    audio_bytes = _decode_audio_base64(audio_base64)
    if not audio_bytes:
        raise AsrError("录音内容为空。")

    client = _build_client()
    file_obj = io.BytesIO(audio_bytes)
    file_obj.name = _guess_filename(mime_type or "", filename)

    try:
        transcript = client.audio.transcriptions.create(
            model=OPENAI_ASR_MODEL,
            file=file_obj,
        )
    except Exception as exc:
        raise AsrError(f"语音转写失败：{exc}") from exc

    text = getattr(transcript, "text", "") or ""
    text = text.strip()
    if not text:
        raise AsrError("语音转写未返回有效文本。")
    return text
