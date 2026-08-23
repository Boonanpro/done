"""
アプリサンドボックス本体 — 業務系ルーターを束ねた FastAPI アプリ

ダンコア（port 9000）が SandboxManager.start() で起動する。
コード変更時はダンコアの /api/v1/sandbox/restart で安全に再起動できる。
"""
from __future__ import annotations

import asyncio
import logging
import os
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
from app.api.voicelog_routes import router as voicelog_router
from app.api.inquiry_routes import router as inquiry_router
from app.api.aix_dashboard_routes import router as aix_dashboard_router
from app.api.publish_routes import router as publish_router
from app.api.salonboard_styleup_routes import router as salonboard_styleup_router
from app.api.salonboard_credentials_routes import router as salonboard_credentials_router
from app.api.client_messaging_routes import router as client_messaging_router
from app.api.bookings_routes import router as bookings_router
from app.api.video_review_routes import router as video_review_router
from app.api.production_asset_routes import router as production_asset_router

logger = logging.getLogger(__name__)


# --- 起動時セルフチェック ----------------------------------------------------
# 「機能が使われた瞬間に初めて壊れていると分かる」事故の根治。ユーザー要求の
# 実行経路で遅延importされる主要モジュールを起動時に全て読み込み、壊れていれば
# 起動ログに全文と /health に理由を出す。auto_deploy 直後・サンドボックス再起動
# 直後に必ず走るので、書きかけコードの混入はユーザーが指示を出す前に検知される。
SELFCHECK_FAILURES: list[str] = []

_SELFCHECK_MODULES = [
    # ダンに指示（編集エージェント）の遅延import連鎖
    "app.agent.cli_runner",
    "app.services.timeline_agent",
    "app.services.timeline_commands",
    "app.services.timeline_context",
    "app.services.timeline_draft",
    # 制作ジョブ・実行系
    "app.services.run_service",
]


def _boot_selfcheck() -> None:
    import importlib
    import traceback

    SELFCHECK_FAILURES.clear()
    for name in _SELFCHECK_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 — 何で壊れていても検知が仕事
            SELFCHECK_FAILURES.append(f"{name}: {exc}")
            logger.critical("起動セルフチェック失敗 %s\n%s", name, traceback.format_exc())
    if SELFCHECK_FAILURES:
        logger.critical(
            "SELFCHECK FAILED (%d件) — この状態ではダンへの指示が失敗します: %s",
            len(SELFCHECK_FAILURES),
            "; ".join(SELFCHECK_FAILURES),
        )
    else:
        logger.info("起動セルフチェック OK (%d modules)", len(_SELFCHECK_MODULES))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("sandbox started")
    _boot_selfcheck()
    try:
        from app.tools.publish_site.orchestrator import recover_paid_domain_registrations
        resumed = await recover_paid_domain_registrations()
        if resumed:
            logger.info("resumed %s paid domain registration(s)", resumed)
    except Exception:
        logger.exception("paid domain registration recovery failed")
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
app.include_router(voicelog_router, prefix="/api/v1")
app.include_router(inquiry_router, prefix="/api/v1")
app.include_router(aix_dashboard_router, prefix="/api/v1")
app.include_router(publish_router, prefix="/api/v1")
app.include_router(salonboard_styleup_router, prefix="/api/v1")
app.include_router(salonboard_credentials_router, prefix="/api/v1")
app.include_router(bookings_router, prefix="/api/v1")
app.include_router(video_review_router, prefix="/api/v1")
app.include_router(production_asset_router, prefix="/api/v1")
app.include_router(client_messaging_router)  # router defines its own /api/v1 prefix


@app.get("/api/v1/proposals/{filename}")
async def serve_proposal_html(filename: str):
    """HTMLプレゼンファイルを認証不要で直接サーブ（URLリンクから別タブで開く用）"""
    if not filename.endswith(".html"):
        raise HTTPException(status_code=400, detail="Only .html files are supported")
    project_root = Path(__file__).resolve().parent.parent.parent
    proposals_dir = Path(
        os.environ.get("DAN_CLI_WORKSPACE", str(project_root / ".dan-workspace"))
    ).joinpath("proposals").resolve()
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
    if SELFCHECK_FAILURES:
        return {
            "status": "degraded",
            "service": "sandbox",
            "environment": settings.APP_ENV,
            "broken_modules": SELFCHECK_FAILURES,
        }
    return {"status": "healthy", "service": "sandbox", "environment": settings.APP_ENV}
