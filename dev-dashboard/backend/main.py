"""
Dev Dashboard Backend - FastAPI Application
"""
import sys
from pathlib import Path

# ダンのプロジェクトをパスに追加（Supabaseクライアント等を再利用）
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# 重要: 他のインポートより先にconfigをインポートして.envを読み込む
from config import PORT, CORS_ORIGINS  # noqa: E402

import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import Response  # noqa: E402

from routes.issues import router as issues_router  # noqa: E402


app = FastAPI(
    title="Dev Dashboard API",
    description="ダンが記録したイシューを管理するAPI",
    version="1.0.0",
)


@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    """CORS処理ミドルウェア"""
    # OPTIONSプリフライトリクエストの処理
    if request.method == "OPTIONS":
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Max-Age": "86400",
            },
        )

    # 通常のリクエストを処理
    response = await call_next(request)

    # CORSヘッダーを追加
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"

    return response

# ルーター登録
app.include_router(issues_router, prefix="/api")


@app.get("/health")
async def health_check():
    """ヘルスチェック"""
    return {"status": "healthy", "service": "dev-dashboard"}


if __name__ == "__main__":
    print(f"Starting Dev Dashboard Backend on port {PORT}...")
    uvicorn.run(
        app,  # 文字列ではなく直接appオブジェクトを渡す
        host="127.0.0.1",
        port=PORT,
        reload=False,  # リロード無効
    )
