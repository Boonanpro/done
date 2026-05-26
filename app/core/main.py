"""
ダンコア — port 9000 で起動する不変プロセス

Phase 1 ではスケルトンのみ。
チャットや認証ルーターは Phase 2 でこちらに移管する。
"""
from __future__ import annotations

import logging
import sys
import asyncio

# Windows: ProactorEventLoop（subprocess 生成に必須）
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.api.sandbox_routes import router as sandbox_router, set_manager
from app.core.sandbox_manager import SandboxManager

# ダンコアが受け持つルーター（チャット・認証・ボイス・エージェント）
from app.api.chat_routes import router as chat_router
from app.api.credentials_routes import router as credentials_router
from app.api.voice_routes import router as voice_router, ws_router as voice_ws_router
from app.api.gemini_voice_routes import router as gemini_voice_router
from app.api.realtime_routes import router as realtime_router, ws_router as realtime_ws_router
from app.api.public_chat_routes import router as public_chat_router

logger = logging.getLogger(__name__)

import os

DAN_CORE_PORT = int(os.environ.get("DAN_CORE_PORT", 9000))
# Phase 5 swap 後は 8000 が想定値。テスト時は DAN_SANDBOX_PORT=8002 で起動できる。
SANDBOX_PORT = int(os.environ.get("DAN_SANDBOX_PORT", 8000))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # WSS プロキシ（モバイル用 WebSocket 中継、port 8443）
    wss_server = None
    try:
        from app.wss_proxy import start_wss_proxy
        wss_server = await start_wss_proxy()
    except Exception as e:
        logger.warning("WSS proxy failed to start: %s", e)

    manager = SandboxManager(port=SANDBOX_PORT)
    set_manager(manager)
    logger.info("dan_core started (sandbox manager ready, port=%s)", SANDBOX_PORT)

    # サンドボックスを自動起動（DAN_AUTO_START_SANDBOX=0 で無効化可能）
    auto_start = os.environ.get("DAN_AUTO_START_SANDBOX", "1") != "0"
    if auto_start:
        try:
            manager.start()
            healthy = manager.wait_until_healthy(timeout=20.0)
            if healthy:
                logger.info("sandbox auto-started and healthy on port %s", SANDBOX_PORT)
            else:
                logger.warning("sandbox started but not healthy within 20s")
        except RuntimeError as e:
            logger.warning("sandbox auto-start failed: %s", e)

    # 続報ポーラー: 予約された follow-up を期限到来時に発火し、ダンを再起動して
    # チャットに報告させる（ターン制エージェントが「完了したら報告します」を守れる
    # ようにする土台）。失敗してもコア起動は妨げない。
    try:
        from app.services.followup_poller import start_poller
        start_poller()
    except Exception as e:
        logger.warning("follow-up poller failed to start: %s", e)

    yield

    # シャットダウン時にサンドボックスも止める
    try:
        manager.stop()
    except Exception as e:
        logger.warning("failed to stop sandbox during shutdown: %s", e)

    if wss_server:
        wss_server.close()


app = FastAPI(
    title="Dan Core",
    description="ダン本体（チャット・LLM・スキル実行）。再起動しない不変プロセス。",
    version="0.1.0",
    lifespan=lifespan,
)


ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
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

app.include_router(sandbox_router)
app.include_router(chat_router, prefix="/api/v1")
app.include_router(credentials_router, prefix="/api/v1")
app.include_router(voice_router)  # /api/v1/voice prefix が router 側に
app.include_router(voice_ws_router)
app.include_router(gemini_voice_router)
app.include_router(realtime_router)  # /api/v1/realtime prefix は router 側に定義
app.include_router(realtime_ws_router)  # /ws/realtime-delegate
app.include_router(public_chat_router, prefix="/api/v1")


@app.get("/")
async def root() -> dict:
    return {"status": "ok", "service": "dan-core", "port": DAN_CORE_PORT}


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy", "service": "dan-core", "environment": settings.APP_ENV}
