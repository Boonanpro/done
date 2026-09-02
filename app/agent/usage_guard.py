"""Max プランの使用量を見て Fable 専用週次枠の枯渇を検知する。

Fable は全モデル共通の週次枠とは別に **Fable 専用の週次枠** を持つ
(2026-09-02 確認)。全部屋を Fable 既定にすると先に詰まるのはこちらなので、
専用枠が閾値 (既定 90%) を超えたら `_resolve_cli_model` が Opus に退避する。

情報源: Claude Code の OAuth トークン (`~/.claude/.credentials.json`) で
`GET https://api.anthropic.com/api/oauth/usage`。`limits[]` の
`kind=weekly_scoped` かつ `scope.model.display_name == "Fable"` の percent。

設計:
- リクエスト経路 (`_resolve_cli_model`) を**絶対にブロックしない**。
  取得はデーモンスレッドで行い、呼び出し側は直近のキャッシュ値を返す。
  (サンドボックスの同期呼び出しがイベントループを止めた前例あり)
- 取得失敗時は「枯渇していない」扱い (= Fable のまま)。誤退避より
  実行継続を優先する。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_REFRESH_SECONDS = 300  # 5分に1回で十分 (週次枠は緩やかにしか動かない)
_HTTP_TIMEOUT = 10

_lock = threading.Lock()
_state: Dict[str, Any] = {
    "fetched_at": 0.0,
    "fable_weekly_pct": None,   # Optional[float]
    "session_pct": None,
    "weekly_all_pct": None,
    "refreshing": False,
    "last_error": None,
}
_last_logged_exhausted: Optional[bool] = None


def fallback_threshold_pct() -> float:
    raw = (os.environ.get("DAN_FABLE_FALLBACK_PCT") or "").strip()
    try:
        return float(raw) if raw else 90.0
    except ValueError:
        return 90.0


def _read_oauth_token() -> Optional[str]:
    try:
        path = Path.home() / ".claude" / ".credentials.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return (data.get("claudeAiOauth") or {}).get("accessToken") or None
    except Exception as e:  # noqa: BLE001
        logger.debug("usage_guard: credentials read failed: %s", e)
        return None


def fetch_usage() -> Optional[Dict[str, Any]]:
    """使用量 JSON を同期取得する (テスト/診断用。経路からは呼ばない)。"""
    token = _read_oauth_token()
    if not token:
        return None
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "dan-usage-guard",
        },
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_limits(usage: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """limits[] から関心のある percent を抜く。"""
    out: Dict[str, Optional[float]] = {
        "fable_weekly_pct": None, "session_pct": None, "weekly_all_pct": None,
    }
    for lim in usage.get("limits") or []:
        if not isinstance(lim, dict):
            continue
        kind = lim.get("kind")
        pct = lim.get("percent")
        if not isinstance(pct, (int, float)):
            continue
        if kind == "session":
            out["session_pct"] = float(pct)
        elif kind == "weekly_all":
            out["weekly_all_pct"] = float(pct)
        elif kind == "weekly_scoped":
            model = ((lim.get("scope") or {}).get("model") or {})
            name = str(model.get("display_name") or "").lower()
            if "fable" in name:
                out["fable_weekly_pct"] = float(pct)
    return out


def _refresh_worker() -> None:
    try:
        usage = fetch_usage()
        parsed = parse_limits(usage) if usage else {}
        with _lock:
            if usage:
                _state.update(parsed)
                _state["last_error"] = None
            else:
                _state["last_error"] = "no token"
            _state["fetched_at"] = time.time()
    except Exception as e:  # noqa: BLE001
        with _lock:
            _state["last_error"] = str(e)[:200]
            _state["fetched_at"] = time.time()
        logger.warning("usage_guard: fetch failed: %s", e)
    finally:
        with _lock:
            _state["refreshing"] = False


def _maybe_refresh_async() -> None:
    with _lock:
        stale = (time.time() - _state["fetched_at"]) > _REFRESH_SECONDS
        if not stale or _state["refreshing"]:
            return
        _state["refreshing"] = True
    threading.Thread(target=_refresh_worker, name="dan-usage-guard", daemon=True).start()


def snapshot() -> Dict[str, Any]:
    with _lock:
        return dict(_state)


def fable_quota_exhausted() -> bool:
    """Fable 専用週次枠が閾値以上なら True。非ブロッキング。

    初回呼び出しはバックグラウンド取得を開始して False を返す (未知=継続)。
    """
    global _last_logged_exhausted
    _maybe_refresh_async()
    with _lock:
        pct = _state["fable_weekly_pct"]
    exhausted = pct is not None and pct >= fallback_threshold_pct()
    if exhausted != _last_logged_exhausted:
        _last_logged_exhausted = exhausted
        if exhausted:
            logger.warning(
                "usage_guard: Fable weekly quota %.0f%% >= %.0f%% — falling back to opus",
                pct, fallback_threshold_pct(),
            )
        elif pct is not None:
            logger.info("usage_guard: Fable weekly quota %.0f%% — fable allowed", pct)
    return exhausted
