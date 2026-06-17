# -*- coding: utf-8 -*-
"""Background poller that ingests inbound email and routes replies.

Runs as a single asyncio task inside dan-core. Every POLL_INTERVAL it:
  1. fetch_all(owner) で Gmail/iCloud から新着メールを取り込み、detected_messages
     と dan-notion inbox に投入する（従来は手動トリガーのみだった部分の自動化）。
  2. 未ルーティングの受信メールを external_message_routing で照合し、ダンの送信
     台帳(external_message_routes)に一致するものだけ「返信案(reply)」提案を作る。
     一致しない受信(コールド/メルマガ等)は inbox に残るだけで通知タブを汚さない。

照合できるのは「送信時に record_outbound で記録された相手からの返信」だけ。
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.getenv("DAN_EMAIL_POLL_INTERVAL", "180"))  # 秒
MAX_ROUTE_PER_CYCLE = 3   # 草案生成(CLI)が重いので1サイクルの照合上限
# 取り込みが新しいものだけ照合対象にする。過去メールの大量バックログを掘り起こして
# 古い用件を「新規返信案」として今さら浮上させないためのカットオフ。
MAX_AGE_HOURS = int(os.getenv("DAN_EMAIL_ROUTE_MAX_AGE_HOURS", "72"))

_started = False
_task: Optional["asyncio.Task"] = None


def _enabled() -> bool:
    return os.getenv("DAN_EMAIL_POLLER_ENABLED", "true").lower() not in {"0", "false", "no", "off"}


async def _ingest(owner_id: str) -> None:
    """IMAP fetch_all で新着メールを取り込む（best-effort）。"""
    try:
        from app.services.imap_email_service import fetch_all
        results = await fetch_all(owner_id)
        fetched = sum(r.get("fetched", 0) for r in (results or []))
        if fetched:
            logger.info("[email] ingested %d new message(s)", fetched)
    except Exception as e:  # noqa: BLE001
        logger.warning("[email] ingest failed: %s", e)


def _unrouted_messages(owner_id: str) -> List[Dict[str, Any]]:
    """未ルーティング・照合未試行の受信メールを取得（同期）。"""
    from app.services.supabase_client import get_supabase_client
    sb = get_supabase_client().client
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)).isoformat()
    rows = (
        sb.table("detected_messages")
        .select("*")
        .eq("user_id", owner_id)
        .eq("source", "gmail")
        .is_("routed_room_id", "null")
        .gte("created_at", cutoff)  # 取り込みが新しいものだけ（過去バックログを掘り起こさない）
        .order("created_at", desc=True)
        .limit(20)
        .execute()
        .data
        or []
    )
    # processing_result.routing_attempted が立っていないものだけ
    out = []
    for r in rows:
        pr = r.get("processing_result") or {}
        if not pr.get("routing_attempted"):
            out.append(r)
    return out[:MAX_ROUTE_PER_CYCLE]


def _mark_attempted(message_id: str) -> None:
    from app.services.supabase_client import get_supabase_client
    sb = get_supabase_client().client
    cur = sb.table("detected_messages").select("processing_result").eq("id", message_id).execute().data
    pr = (cur[0].get("processing_result") if cur else None) or {}
    pr["routing_attempted"] = True
    sb.table("detected_messages").update({"processing_result": pr}).eq("id", message_id).execute()


async def _route_new(owner_id: str) -> None:
    from app.services.external_message_routing import (
        STRONG_REASONS,
        get_external_message_routing_service,
    )
    svc = get_external_message_routing_service()
    msgs = await asyncio.to_thread(_unrouted_messages, owner_id)
    for msg in msgs:
        try:
            # ① 機械照合
            match = await asyncio.to_thread(svc.find_route, msg)
            if match and match.reason in STRONG_REASONS:
                # 強い一致(ヘッダ/合言葉)＝事実なので即確定
                result = await svc.apply_match(msg, match)
            else:
                # 弱い一致(送信者+直近) or 未一致 → 内容判定で漏れ拾い/ダブルチェック
                from app.services.inbound_content_router import classify_and_route
                result = await classify_and_route(msg, svc, weak_match=match)

            if result:
                logger.info("[email] routed msg=%s -> %s", msg.get("id"), result.get("decision") or result.get("reason"))
            else:
                # 対応不要/非メール/判定不能 → 再試行しないよう印（inbox には残る）
                await asyncio.to_thread(_mark_attempted, msg["id"])
        except Exception as e:  # noqa: BLE001
            logger.warning("[email] route failed for msg=%s: %s", msg.get("id"), e)


async def _tick() -> None:
    from app.services.owner import resolve_owner_user_id
    owner_id = resolve_owner_user_id()
    if not owner_id:
        return
    await _ingest(owner_id)
    await _route_new(owner_id)


async def poller_loop() -> None:
    logger.info("[email] poller started (interval=%ss)", POLL_INTERVAL)
    while True:
        try:
            if _enabled():
                await _tick()
        except Exception as e:  # noqa: BLE001
            logger.error("[email] tick error: %s", e)
        await asyncio.sleep(POLL_INTERVAL)


def start_poller() -> Optional["asyncio.Task"]:
    """Start the email poller once. Safe to call from FastAPI lifespan startup."""
    global _started, _task
    if _started:
        return _task
    if not _enabled():
        logger.info("[email] poller disabled (DAN_EMAIL_POLLER_ENABLED)")
        return None
    _started = True
    _task = asyncio.create_task(poller_loop())
    return _task
