"""
/api/v1/sandbox/* — サンドボックス制御API

ダンコアからアプリサンドボックス（port 8000系）を操作する内部エンドポイント。
ダンが「コード変えたから再起動して」という時にこれを叩く。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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


class RestartRequest(BaseModel):
    """テスト用に env を一時注入できる。例: {"extra_env": {"DAN_DEV_NO_AUTH": "1"}}"""
    extra_env: Optional[dict[str, str]] = None
    force: bool = False


def _running_production_jobs() -> list[str]:
    """制作ジョブ実行中のサンドボックス再起動はユーザーの編集作業を全損させる
    （実発生2回: CTAジョブ・サイドスーパージョブが 'server restarted while running' で死亡）。
    呼び出し元が誰でも（別開発セッション・auto_deploy・手動curl）守れるようAPI側で門番する。"""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "uploads" / "production-assets"
    running: list[str] = []
    if not root.exists():
        return running
    for jp in root.glob("*/jobs.json"):
        try:
            jobs = json.loads(jp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for j in jobs:
            if isinstance(j, dict) and j.get("status") == "running":
                running.append(f"{jp.parent.name[:12]}:{str(j.get('id'))[:8]}")
    return running


@router.post("/restart")
async def restart_sandbox(payload: Optional[RestartRequest] = None) -> dict:
    mgr = _require_manager()
    extra = payload.extra_env if payload else None
    force = bool(payload.force) if payload else False
    if not force:
        running = _running_production_jobs()
        if running:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"制作ジョブ実行中のため再起動を拒否しました: {', '.join(running[:5])} — "
                    "ジョブ完了を待つか、全損を許容するなら {\"force\": true} で再実行してください"
                ),
            )
    try:
        mgr.restart(extra_env=extra)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    mgr.wait_until_healthy(timeout=15.0)
    return _serialize(mgr.status())
