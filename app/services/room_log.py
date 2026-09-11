# -*- coding: utf-8 -*-
"""部屋ログ（chat_messages）への追記の唯一の入口。

原則: 部屋に起きたことは一本の追記専用ログであり、書き手は core ただ一人。
ツール（MCP 子プロセス）・サンドボックス・ポーラーなど core の外で動く
コードが DB に直接書くと、core の押し込みフィード（room_feed）はそれを
知らず、画面はメッセージ一覧を取り直すまで気づけない。送信案カードが
「出したのに見えない」（2026-09-11）の直接原因がこれ。

- core 内: insert → 配信記録 → フィード配信 を同期で行う（append_local）。
- core 外: core の内部API（loopback 限定）に頼む。core に届かない時だけ
  直接 insert し、その場合もフィード配信は room_feed が core へ転送する。
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CORE_TIMEOUT_S = 5.0


def core_base_url() -> str:
    port = os.environ.get("DAN_CORE_PORT", "9000")
    return f"http://127.0.0.1:{port}"


def _post_core(path: str, payload: dict[str, Any], timeout: float = _CORE_TIMEOUT_S) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    req = urllib.request.Request(
        core_base_url() + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (loopback only)
        raw = resp.read().decode("utf-8") or "{}"
    return json.loads(raw)


def append_local(
    room_id: str,
    content: str,
    sender_type: str = "ai",
    sender_id: Optional[str] = None,
    message_id: Optional[str] = None,
) -> dict[str, Any]:
    """core プロセス内の実体。insert → last_message/未読の更新 → フィード配信。"""
    from app.services.supabase_client import get_supabase_client
    from app.services.chat_service import record_message_delivery_sync
    from app.services.room_feed import publish_message

    sb = get_supabase_client().client
    msg_id = message_id or str(uuid.uuid4())
    row = {
        "id": msg_id,
        "room_id": room_id,
        "sender_id": sender_id,
        "sender_type": sender_type,
        "content": content,
    }
    res = sb.table("chat_messages").insert(row).execute()
    saved = dict((res.data or [row])[0])
    try:
        record_message_delivery_sync(sb, room_id, msg_id, sender_id=sender_id, content=content)
    except Exception:  # noqa: BLE001
        logger.warning("room_log: delivery record failed room=%s", room_id[:8], exc_info=True)
    try:
        publish_message(room_id, saved)
    except Exception:  # noqa: BLE001
        logger.warning("room_log: publish failed room=%s", room_id[:8], exc_info=True)
    return saved


def append(
    room_id: str,
    content: str,
    sender_type: str = "ai",
    sender_id: Optional[str] = None,
) -> dict[str, Any]:
    """どのプロセスからでも呼べる追記。core 内なら直接、外なら core に委譲する。"""
    if not room_id:
        raise ValueError("room_id is required")
    from app.services import room_feed

    if room_feed.in_core_process():
        return append_local(room_id, content, sender_type=sender_type, sender_id=sender_id)
    try:
        data = _post_core(
            f"/api/v1/chat/internal/rooms/{room_id}/messages",
            {"content": content, "sender_type": sender_type, "sender_id": sender_id},
        )
        msg = data.get("message") if isinstance(data, dict) else None
        if msg and msg.get("id"):
            return msg
        raise RuntimeError(f"unexpected core reply: {str(data)[:200]}")
    except Exception as e:  # noqa: BLE001
        logger.warning("room_log: core append unavailable (%s); writing directly room=%s", e, room_id[:8])
        return append_local(room_id, content, sender_type=sender_type, sender_id=sender_id)
