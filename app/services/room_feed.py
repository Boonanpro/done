# -*- coding: utf-8 -*-
"""本人向けの新着ストリーム（push 同期の要）。

「部屋を開いた時に取りに行く」から「変化が起きた瞬間に押し込む」へ。
メッセージが保存されるたびに、その部屋のメンバー全員のストリームへ同じ
メッセージを流す。ブラウザ/APK は開いている間これを1本つなぎ、手元の写し
（react-query の永続キャッシュ / 端末内ファイル）を常に最新に保つ。
部屋を開いた時には写しが最新なので「最新の状態を取得中…」が要らなくなる。

- publish_message はスレッドから呼べる（CLI の保存はワーカースレッド）。
  購読者のイベントループへ call_soon_threadsafe で渡す。
- 購読者がいない時は何もしない（メンバー照会もしない）。
- 落ちた/閉じていた間の分は /chat/rooms/delta（since 以降の全部屋の差分）で追いつく。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import urllib.request
from collections import defaultdict
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger(__name__)

# 購読者は core プロセスにしかいない。core 以外（MCP 子プロセス・サンドボックス・
# ポーラー）で publish_message が呼ばれたら、core の内部APIへ転送する。
# core は起動時に mark_core_process() を呼ぶ。
_IN_CORE = False
_FORWARD_TIMEOUT_S = 2.0


def mark_core_process() -> None:
    global _IN_CORE
    _IN_CORE = True


def in_core_process() -> bool:
    return _IN_CORE


def _core_base_url() -> str:
    return f"http://127.0.0.1:{os.environ.get('DAN_CORE_PORT', '9000')}"


def _post_to_core(path: str, payload: dict) -> int:
    """core 外から: core の内部APIに渡して配信してもらう。届かなくても例外にしない。"""
    try:
        req = urllib.request.Request(
            f"{_core_base_url()}/api/v1/chat/internal/{path}",
            data=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_FORWARD_TIMEOUT_S) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8") or "{}")
        return int(data.get("delivered") or 0)
    except Exception as e:  # noqa: BLE001
        logger.debug("room_feed: forward to core failed (%s): %s", path, e)
        return 0


def _forward_to_core(room_id: str, msg: dict) -> int:
    """core 外から: 保存済みの行を core に渡して配信してもらう。"""
    return _post_to_core(f"rooms/{room_id}/messages", {"already_saved": True, "message": msg})


_lock = threading.Lock()
# user_id → {queue: loop}
_subs: dict[str, dict[asyncio.Queue, asyncio.AbstractEventLoop]] = defaultdict(dict)
# room_id → (expires_at, [user_id, ...])
_members_cache: dict[str, tuple[float, list[str]]] = {}
_MEMBERS_TTL = 600.0
_QUEUE_MAX = 500


def subscriber_count(user_id: Optional[str] = None) -> int:
    with _lock:
        if user_id:
            return len(_subs.get(user_id, {}))
        return sum(len(q) for q in _subs.values())


def _room_members(room_id: str) -> list[str]:
    now = time.time()
    hit = _members_cache.get(room_id)
    if hit and hit[0] > now:
        return hit[1]
    try:
        from app.services.supabase_client import get_supabase_client

        rows = (
            get_supabase_client().client.table("chat_room_members")
            .select("user_id").eq("room_id", room_id).execute().data or []
        )
        users = [r["user_id"] for r in rows if r.get("user_id")]
    except Exception as e:  # noqa: BLE001
        logger.debug("room_feed: member lookup failed for %s: %s", room_id[:8], e)
        users = []
    _members_cache[room_id] = (now + _MEMBERS_TTL, users)
    return users


def invalidate_room_members(room_id: str) -> None:
    _members_cache.pop(room_id, None)


def _slim_message(msg: dict) -> dict:
    """配信用に MessageResponse と同じ形へ（一覧APIと同じ軽量化）。"""
    out = {
        "id": msg.get("id"),
        "room_id": msg.get("room_id"),
        "sender_id": msg.get("sender_id"),
        "sender_name": msg.get("sender_name") or ("ダン" if msg.get("sender_type") == "ai" else "Unknown"),
        "sender_type": msg.get("sender_type"),
        "content": msg.get("content"),
        "created_at": msg.get("created_at"),
    }
    if msg.get("reply_to"):
        out["reply_to_id"] = msg["reply_to"]
    if msg.get("ai_context"):
        try:
            from app.services.chat_service import ChatService

            out["ai_context"] = ChatService._slim_ai_context(msg["ai_context"])
        except Exception:  # noqa: BLE001
            out["ai_context"] = msg["ai_context"]
    return out


def publish(user_ids: list[str], event: dict) -> int:
    """指定ユーザーの購読者へイベントを渡す。スレッドセーフ。配った本数を返す。"""
    delivered = 0
    with _lock:
        targets = []
        for uid in user_ids:
            targets.extend(list(_subs.get(uid, {}).items()))
    for queue, loop in targets:
        try:
            if queue.qsize() >= _QUEUE_MAX:
                continue  # 詰まった購読者は捨てる（再接続時に delta で追いつく）
            loop.call_soon_threadsafe(queue.put_nowait, event)
            delivered += 1
        except Exception:  # noqa: BLE001
            pass
    return delivered


def publish_run(run: dict) -> int:
    """実行記録（agent_runs）の状態を書いた直後に、書いた行を渡して呼ぶ。その部屋の画面は一覧の「ダンが作業中」を
    次の定期取得（10秒ごと）を待たずに合わせる。裏で進む作業（ジョブ）はチャットの作業中ではないので知らせない。
    core 外なら core へ転送。購読者がいなければ何もしない。"""
    room_id, project_id = run.get("room_id"), run.get("project_id")
    if not room_id or not project_id:
        return 0
    from app.services.run_service import background

    if background(run):
        return 0
    if not _IN_CORE:
        return _post_to_core("runs", {k: run.get(k) for k in ("room_id", "project_id", "state", "metadata")})
    if subscriber_count() == 0:
        return 0
    event = {"type": "run", "project_id": project_id, "room_id": room_id,
             "running": run.get("state") == "running", "at": time.time()}
    return publish(_room_members(room_id), event)


def publish_all(event: dict) -> int:
    """Every open screen, whoever it belongs to (the core is about to restart)."""
    with _lock:
        users = list(_subs)
    return publish(users, event)


def publish_message(room_id: str, msg: dict) -> int:
    """メッセージ保存直後に呼ぶ。core 外なら core へ転送。購読者がいなければ即 return（DB照会もしない）。"""
    if not room_id:
        return 0
    if not _IN_CORE:
        return _forward_to_core(room_id, msg)
    if subscriber_count() == 0:
        return 0
    users = _room_members(room_id)
    if not users:
        return 0
    event = {"type": "message", "room_id": room_id, "message": _slim_message(msg), "at": time.time()}
    return publish(users, event)


async def subscribe(user_id: str) -> AsyncIterator[dict]:
    """購読。ジェネレータが閉じられたら登録解除。"""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    with _lock:
        _subs[user_id][queue] = loop
    try:
        while True:
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                yield ev
            except asyncio.TimeoutError:
                yield {"type": "ping", "at": time.time()}
    finally:
        with _lock:
            _subs[user_id].pop(queue, None)
            if not _subs[user_id]:
                _subs.pop(user_id, None)
