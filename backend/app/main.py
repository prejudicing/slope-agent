"""FastAPI 应用入口。

开发时可只作为 API 服务运行；生产构建存在时会直接挂载 frontend/dist。
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api import router

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    # Capacitor Android WebView uses http://localhost as the app origin, while
    # desktop/mobile browsers may access the dev server from LAN IPs. Use an
    # origin regex instead of "*" + credentials so native-app cross-origin
    # requests and browser debugging can both pass CORS cleanly.
    allow_origins=["http://localhost", "https://localhost", "capacitor://localhost"],
    allow_origin_regex=(
        r"^https?://("
        r"localhost|127\.0\.0\.1|"
        r"10(?:\.\d{1,3}){3}|"
        r"172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}|"
        r"192\.168(?:\.\d{1,3}){2}"
        r")(?::\d+)?$"
    ),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

# 如果前端已经执行过 build，则后端同时提供静态页面，便于用同一个端口访问。
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
