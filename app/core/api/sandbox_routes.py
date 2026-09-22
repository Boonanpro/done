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
    if _recent_voice_sessions():
        raise HTTPException(409,detail='音声会話中のため停止を延期しました。')
    return _serialize(_require_manager().stop())


class RestartRequest(BaseModel):
    """テスト用に env を一時注入できる。例: {"extra_env": {"DAN_DEV_NO_AUTH": "1"}}"""
    extra_env: Optional[dict[str, str]] = None
    force: bool = False


def _recent_voice_sessions(root=None, now=None) -> list[str]:
    """Client usage/events renew activity; crashed clients expire without locking forever."""
    import json
    import time
    from pathlib import Path
    root = Path(root) if root is not None else Path(__file__).resolve().parents[3] / 'uploads' / 'production-assets'
    now = time.time() if now is None else now
    active=[]
    for path in root.glob('*/assistant/events/*.jsonl'):
        try:
            if now-path.stat().st_mtime>90:continue
            with path.open('rb') as stream:
                stream.seek(max(0,path.stat().st_size-65536))
                lines=stream.read().decode('utf-8',errors='replace').splitlines()
            for line in reversed(lines):
                try:event=json.loads(line)
                except (ValueError,TypeError):continue
                kind=event.get('type','')
                if kind=='live_session_closed':break
                if kind in {'live_runtime','live_usage','user_transcript','assistant_transcript','voice_output_started'}:
                    active.append(path.parents[2].name);break
        except OSError:
            continue
    return sorted(set(active))+_live_phone_calls(now)


def _live_phone_calls(now=None, log=None) -> list[str]:
    """Phone calls whose server-side sideband is attached (voice_sideband writes sideband_attached / sideband_closed).
    A sandbox restart kills that connection mid-call (2026-09-22 17:38: the owner's test call ended in 「ダンへの通信が
    切れました」); the editor-only check above never saw phone calls."""
    import json
    import time
    from pathlib import Path
    log = Path(log) if log is not None else Path(__file__).resolve().parents[3] / '.tmp' / 'voice-sideband.jsonl'
    now = time.time() if now is None else now
    open_calls: dict[str, float] = {}
    try:
        with log.open('rb') as stream:
            stream.seek(max(0, log.stat().st_size-262144))
            lines = stream.read().decode('utf-8', errors='replace').splitlines()
    except OSError:
        return []
    from datetime import datetime
    for line in lines:
        try: row = json.loads(line)
        except (ValueError, TypeError): continue
        try: at = datetime.fromisoformat(row.get('at', '')).timestamp()
        except (ValueError, TypeError): continue
        sid = str(row.get('session_id') or '')
        if row.get('phase') == 'sideband_attached': open_calls[sid] = (at, row.get('pid'))
        elif row.get('phase') in ('sideband_closed', 'sideband_failed'): open_calls.pop(sid, None)
    import psutil
    def alive(at, pid):
        if pid is None: return now-at < 15*60   # rows written before the pid was logged: trusted briefly only
        return psutil.pid_exists(int(pid))   # a call whose sandbox process died (a restart) is over, though it never logged "closed"
    return sorted('call:'+sid[:16] for sid, (at, pid) in open_calls.items() if now-at < 3*3600 and alive(at, pid))


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
    if _recent_voice_sessions():
        raise HTTPException(409,detail='音声会話中のため再起動を延期しました。会話終了後に再実行してください。')
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
