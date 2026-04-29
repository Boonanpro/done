"""
/api/v1/sandbox/* — サンドボックス制御API

ダンコアからアプリサンドボックス（port 8000系）を操作する内部エンドポイント。
ダンが「コード変えたから再起動して」という時にこれを叩く。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.sandbox_manager import SandboxManager, SandboxStatus

router = APIRouter(prefix="/api/v1/sandbox", tags=["sandbox"])

# 起動時に main.py で 1 度だけ生成して set_manager() で渡す
_manager: SandboxManager | None = None


def set_manager(manager: SandboxManager) -> None:
    global _manager
    _manager = manager


def _require_manager() -> SandboxManager:
    if _manager is None:
        raise HTTPException(status_code=503, detail="sandbox manager not initialized")
    return _manager


def _serialize(status: SandboxStatus) -> dict:
    return {
        "pid": status.pid,
        "port": status.port,
        "running": status.running,
        "healthy": status.healthy,
        "started_at": status.started_at,
        "log_path": status.log_path,
    }


@router.get("/status")
async def get_status() -> dict:
    return _serialize(_require_manager().status())


@router.post("/start")
async def start_sandbox() -> dict:
    mgr = _require_manager()
    try:
        status = mgr.start()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    mgr.wait_until_healthy(timeout=15.0)
    return _serialize(mgr.status())


@router.post("/stop")
async def stop_sandbox() -> dict:
    return _serialize(_require_manager().stop())


@router.post("/restart")
async def restart_sandbox() -> dict:
    mgr = _require_manager()
    try:
        mgr.restart()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    mgr.wait_until_healthy(timeout=15.0)
    return _serialize(mgr.status())
