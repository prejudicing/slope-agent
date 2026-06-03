from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from fastapi import HTTPException
from fastapi.responses import FileResponse
from PIL import Image, ImageOps


GENERATED_ROOT = Path(__file__).resolve().parents[1] / "generated"
CACHE_ROOT = GENERATED_ROOT / "photo_cache"
ORIGINAL_DIR = CACHE_ROOT / "original"
VARIANT_DIR = CACHE_ROOT / "variants"
REMOTE_BASE = "http://1.13.19.44:8080"
ALLOWED_HOSTS = {"1.13.19.44"}
SIZE_CONFIG = {
    "thumb": (520, 72),
    "preview": (1280, 82),
}


def _safe_remote_url(value: str) -> str:
    raw = unquote(str(value or "").strip())
    if not raw:
        raise HTTPException(status_code=400, detail="empty image path")

    if raw.startswith("/u/mon/"):
        return f"{REMOTE_BASE}{raw}"
    if raw.startswith("u/mon/"):
        return f"{REMOTE_BASE}/{raw}"
    if raw.startswith("/"):
        raise HTTPException(status_code=400, detail="unsupported image path")

    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"}:
        if parsed.hostname not in ALLOWED_HOSTS:
            raise HTTPException(status_code=400, detail="unsupported image host")
        return raw

    return f"{REMOTE_BASE}/u/mon/{raw.lstrip('/')}"


def _cache_key(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return f"{digest}{suffix}"


def _download_original(url: str) -> Path:
    ORIGINAL_DIR.mkdir(parents=True, exist_ok=True)
    target = ORIGINAL_DIR / _cache_key(url)
    if target.exists() and target.stat().st_size > 0:
        return target

    try:
        response = requests.get(url, timeout=(4, 18), stream=True)
        response.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"image download failed: {exc}") from exc

    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=128 * 1024):
            if chunk:
                handle.write(chunk)
    tmp.replace(target)
    return target


def _variant_path(original: Path, size: str) -> Path:
    width, quality = SIZE_CONFIG.get(size, SIZE_CONFIG["thumb"])
    target_dir = VARIANT_DIR / size
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{original.stem}_{width}w_q{quality}.jpg"


def _make_variant(original: Path, size: str) -> Path:
    target = _variant_path(original, size)
    if target.exists() and target.stat().st_size > 0:
        return target

    width, quality = SIZE_CONFIG.get(size, SIZE_CONFIG["thumb"])
    try:
        with Image.open(original) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((width, width * 2), Image.LANCZOS)
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            image.save(target, "JPEG", quality=quality, optimize=True, progressive=True)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"image resize failed: {exc}") from exc
    return target


def get_cached_photo_response(path: str, size: str = "thumb") -> FileResponse:
    url = _safe_remote_url(path)
    original = _download_original(url)

    if size == "original":
        content_type = mimetypes.guess_type(original.name)[0] or "image/jpeg"
        response_path = original
    else:
        response_path = _make_variant(original, size if size in SIZE_CONFIG else "thumb")
        content_type = "image/jpeg"

    return FileResponse(
        response_path,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=2592000",
        },
    )
