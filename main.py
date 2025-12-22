"""
AI Secretary System - Main Entry Point (Phase 6 reload)
"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.routes import router as api_router
from app.api.line_webhook import router as line_webhook_router
from app.api.chat_routes import router as chat_router
from app.api.credentials_routes import router as credentials_router
from app.api.gmail_routes import router as gmail_router
from app.api.detection_routes import router as detection_router
from app.api.content_routes import router as content_router
from app.api.invoice_routes import router as invoice_router

app = FastAPI(
    title="AI Secretary System",
    description="AI秘書システム - メール・LINE仲介、物品購入、支払い自動化",
    version="0.1.0",
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番環境では適切に設定
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ルーター登録
app.include_router(api_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(credentials_router, prefix="/api/v1")
app.include_router(gmail_router, prefix="/api/v1")
app.include_router(detection_router, prefix="/api/v1")
app.include_router(content_router, prefix="/api/v1")
app.include_router(invoice_router, prefix="/api/v1")
app.include_router(line_webhook_router, prefix="/webhook")


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

