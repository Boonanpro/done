"""
AI Secretary System - Main Entry Point (Phase 6 reload)
"""
import sys
import asyncio
from contextlib import asynccontextmanager

# Windows: ProactorEventLoop を明示的に設定（subprocess 生成に必須）
# SelectorEventLoop だと asyncio.create_subprocess_exec が NotImplementedError になる
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.chat_routes import router as chat_router
from app.api.credentials_routes import router as credentials_router
from app.api.gmail_routes import router as gmail_router
from app.api.detection_routes import router as detection_router
from app.api.content_routes import router as content_router
# from app.api.invoice_routes import router as invoice_router  # v3で無効化
from app.api.bank_account_routes import router as bank_account_router
from app.api.otp_routes import router as otp_router
from app.api.voice_routes import router as voice_router, ws_router as voice_ws_router
from app.api.skill_routes import router as skill_router
from app.api.gemini_voice_routes import router as gemini_voice_router
from app.api.project_routes import router as project_router
from app.api.note_routes import router as note_router
from app.api.file_routes import router as file_router


# v3: Executorは不使用（汎用ツールで処理）


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.heartbeat_service import heartbeat_loop, opus_improvement_loop
    heartbeat_task = asyncio.create_task(heartbeat_loop())
    opus_task = asyncio.create_task(opus_improvement_loop())

    # Start WSS proxy for mobile WebSocket access (port 8443)
    wss_server = None
    try:
        from app.wss_proxy import start_wss_proxy
        wss_server = await start_wss_proxy()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("WSS proxy failed to start: %s", e)

    yield

    heartbeat_task.cancel()
    opus_task.cancel()
    if wss_server:
        wss_server.close()


app = FastAPI(
    title="AI Secretary System",
    description="AI秘書システム - メール・LINE仲介、物品購入、支払い自動化",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS設定
# credentials: 'include' を使用する場合、allow_origins に * は使用不可
ALLOWED_ORIGINS = [
    "http://localhost:3000",      # フロントエンド開発サーバー
    "http://127.0.0.1:3000",
    "http://localhost:8000",      # Swagger UI
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ルーター登録
app.include_router(chat_router, prefix="/api/v1")
app.include_router(credentials_router, prefix="/api/v1")
app.include_router(gmail_router, prefix="/api/v1")
app.include_router(detection_router, prefix="/api/v1")
app.include_router(content_router, prefix="/api/v1")
# app.include_router(invoice_router, prefix="/api/v1")  # v3で無効化
app.include_router(bank_account_router, prefix="/api/v1")
app.include_router(otp_router, prefix="/api/v1")
app.include_router(voice_router)  # Already has /api/v1/voice prefix
app.include_router(voice_ws_router)
app.include_router(skill_router, prefix="/api/v1")
app.include_router(gemini_voice_router)
app.include_router(project_router, prefix="/api/v1")
app.include_router(note_router, prefix="/api/v1")
app.include_router(file_router, prefix="/api/v1")



@app.get("/")
async def root():
    """ヘルスチェック用エンドポイント"""
    return {"status": "ok", "message": "AI Secretary System is running"}


@app.get("/health")
async def health_check():
    """詳細なヘルスチェック"""
    return {
        "status": "healthy",
        "environment": settings.APP_ENV,
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.APP_ENV == "development",
    )

