"""
アプリサンドボックス本体 — 業務系ルーターを束ねた FastAPI アプリ

ダンコア（port 9000）が SandboxManager.start() で起動する。
コード変更時はダンコアの /api/v1/sandbox/restart で安全に再起動できる。
"""
from __future__ import annotations

import asyncio
import logging
import sys

# Windows: ProactorEventLoop（subprocess 生成に必須）
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.config import settings

# 業務系ルーター（ユーザーが頻繁にいじるコード）
from app.api.gmail_routes import router as gmail_router
from app.api.detection_routes import router as detection_router
from app.api.content_routes import router as content_router
from app.api.bank_account_routes import router as bank_account_router
from app.api.otp_routes import router as otp_router
from app.api.project_routes import router as project_router
from app.api.note_routes import router as note_router
from app.api.file_routes import router as file_router
from app.api.studio_routes import router as studio_router
from app.api.collab_routes import router as collab_router
from app.api.calendar_routes import router as calendar_router
from app.api.push_routes import router as push_router
from app.api.dan_notion_routes import router as dan_notion_router
from app.api.chat_artifact_routes import router as chat_artifact_router
from app.api.image_generation_routes import router as image_generation_router
from app.api.video_generation_routes import router as video_generation_router
from app.api.inspector_routes import router as inspector_router
from app.api.inspector_overrides_routes import router as inspector_overrides_router
from app.api.inquiry_routes import router as inquiry_router
from app.api.aix_dashboard_routes import router as aix_dashboard_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("sandbox started")
    yield


app = FastAPI(
    title="Dan App Sandbox",
    description="業務系アプリのエンドポイント。ダンコアから再起動可能な可変プロセス。",
    version="0.1.0",
    lifespan=lifespan,
)


ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:9000",
    "http://127.0.0.1:9000",
]
if settings.ALLOWED_ORIGINS:
    ALLOWED_ORIGINS.extend(
        [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 業務系ルーター登録
app.include_router(gmail_router, prefix="/api/v1")
app.include_router(detection_router, prefix="/api/v1")
app.include_router(content_router, prefix="/api/v1")
app.include_router(bank_account_router, prefix="/api/v1")
app.include_router(otp_router, prefix="/api/v1")
app.include_router(project_router, prefix="/api/v1")
app.include_router(note_router, prefix="/api/v1")
app.include_router(file_router, prefix="/api/v1/files")
app.include_router(studio_router, prefix="/api/v1")
app.include_router(collab_router, prefix="/api/v1")
app.include_router(calendar_router, prefix="/api/v1")
app.include_router(push_router, prefix="/api/v1")
app.include_router(dan_notion_router, prefix="/api/v1")
app.include_router(chat_artifact_router, prefix="/api/v1")
app.include_router(image_generation_router, prefix="/api/v1")
app.include_router(video_generation_router, prefix="/api/v1")
app.include_router(inspector_router, prefix="/api/v1")
app.include_router(inspector_overrides_router, prefix="/api/v1")
app.include_router(inquiry_router, prefix="/api/v1")
app.include_router(aix_dashboard_router, prefix="/api/v1")


@app.get("/api/v1/proposals/{filename}")
async def serve_proposal_html(filename: str):
    """HTMLプレゼンファイルを認証不要で直接サーブ（URLリンクから別タブで開く用）"""
    if not filename.endswith(".html"):
        raise HTTPException(status_code=400, detail="Only .html files are supported")
    proposals_dir = Path("D:/dan-workspace/proposals").resolve()
    html_path = (proposals_dir / filename).resolve()
    if not html_path.is_relative_to(proposals_dir):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not html_path.exists() or not html_path.is_file():
        raise HTTPException(status_code=404, detail="Proposal file not found")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/")
async def root() -> dict:
    return {"status": "ok", "service": "sandbox"}


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy", "service": "sandbox", "environment": settings.APP_ENV}
