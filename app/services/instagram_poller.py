# -*- coding: utf-8 -*-
"""Instagram DM の着信を検知し、案件ルームでダンを起こす / 通知タブに出す。

設計（メールと同じ骨格・リスクだけインスタ用に締める）:

  1. 巡回対象アカウントは固定しない。**ダンがDMを送った時に台帳
     (external_message_routes) に記録したアカウント**だけを巡回する。
     送っていないアカウントは一切触らない。
  2. 既定60分間隔＋ゆらぎ。毎正時ぴったりの機械的パターンを避ける。
  3. 台帳に相手(@handle)の記録があれば → 会話の流れを読んでそのルームでダンを
     起こす。無ければ → 通知タブ(dan_proposals)。
  4. ログインはダンの自力ログイン基盤（認証情報 + 2captcha + メールOTP）で
     自動。ユーザーの手は借りない。それでも駄目な時だけ通知で助けを求める。
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.getenv("DAN_IG_POLL_INTERVAL", "3600"))  # 既定60分
JITTER_RATIO = 0.2          # ±20% のゆらぎ
MAX_THREADS_PER_CYCLE = 10  # 1巡回で扱う新着スレッド数の上限
OUTBOUND_LOOKBACK_DAYS = 60  # 何日前までの送信実績のあるアカウントを巡回するか

_started = False
_task: Optional["asyncio.Task"] = None


def _enabled() -> bool:
    return os.getenv("DAN_IG_POLLER_ENABLED", "true").lower() not in {"0", "false", "no", "off"}


def _next_delay() -> float:
    jitter = POLL_INTERVAL * JITTER_RATIO
    return max(60.0, POLL_INTERVAL + random.uniform(-jitter, jitter))


# --------------------------------------------------------------------------
# 台帳（どのアカウントで誰に送ったか）
# --------------------------------------------------------------------------

def _watched_accounts(user_id: str) -> List[str]:
    """巡回すべきインスタアカウント＝最近DMを送った実績のあるアカウント。"""
    from app.services.supabase_client import get_supabase_client
    sb = get_supabase_client().client
    cutoff = (datetime.now(timezone.utc) - timedelta(days=OUTBOUND_LOOKBACK_DAYS)).isoformat()
    rows = (
        sb.table("external_message_routes")
        .select("external_account_id")
        .eq("user_id", user_id)
        .eq("channel", "instagram")
        .gte("last_outbound_at", cutoff)
        .execute()
        .data
        or []
    )
    accounts = {r["external_account_id"] for r in rows if r.get("external_account_id")}
    return sorted(accounts)


def _find_route_for_handle(user_id: str, account: str, handle: str) -> Optional[Dict[str, Any]]:
    """この相手(@handle)にこのアカウントから送った記録を引く。"""
    from app.services.supabase_client import get_supabase_client
    sb = get_supabase_client().client
    rows = (
        sb.table("external_message_routes")
        .select("*")
        .eq("user_id", user_id)
        .eq("channel", "instagram")
        .eq("external_account_id", account)
        .eq("external_recipient_id", handle.lower())
        .order("last_outbound_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


# --------------------------------------------------------------------------
# 既に処理した DM の記録（再通知しない）
# --------------------------------------------------------------------------

def _already_seen(user_id: str, thread_id: str, last_ts: int) -> bool:
    from app.services.supabase_client import get_supabase_client
    sb = get_supabase_client().client
    source_id = f"ig:{thread_id}:{last_ts}"
    rows = (
        sb.table("detected_messages").select("id")
        .eq("user_id", user_id).eq("source", "instagram").eq("source_id", source_id)
        .limit(1).execute().data or []
    )
    return bool(rows)


def _record_detected(user_id: str, account: str, thread: Dict[str, Any],
                     conversation: str = "") -> Dict[str, Any]:
    """検知したDMを detected_messages に保存して返す（メールと同じ器に載せる）。

    conversation があれば、最新1通ではなく会話の流れを本文にする
    （ダンがルームで報告する時に文脈が要るため）。
    """
    from app.services.supabase_client import get_supabase_client
    sb = get_supabase_client().client
    handle = _counterpart(thread)
    row = {
        "user_id": user_id,
        "source": "instagram",
        "source_id": f"ig:{thread['thread_id']}:{thread['last_ts']}",
        "content": conversation or thread.get("last_text") or "",
        "subject": f"Instagram DM: @{handle}" if handle else "Instagram DM",
        "sender_info": {"from": f"@{handle}" if handle else "(不明)", "handle": handle,
                        "account": account, "provider": "instagram"},
        "metadata": {"thread_id": thread["thread_id"], "account": account,
                     "item_type": thread.get("item_type"), "read_state": thread.get("read_state"),
                     "participants": thread.get("participants")},
        "status": "pending",
    }
    result = sb.table("detected_messages").insert(row).execute()
    return result.data[0] if result.data else row


def _counterpart(thread: Dict[str, Any]) -> Optional[str]:
    parts = thread.get("participants") or []
    return parts[0] if parts else None


# --------------------------------------------------------------------------
# 通知（案件が特定できなかった時）
# --------------------------------------------------------------------------

def _create_proposal(user_id: str, account: str, thread: Dict[str, Any], detected_id: str) -> None:
    from app.services.supabase_client import get_supabase_client
    sb = get_supabase_client().client
    handle = _counterpart(thread) or "(不明)"
    preview = (thread.get("last_text") or "").strip()
    if thread.get("item_type") and thread["item_type"] != "text":
        preview = preview or f"({thread['item_type']})"
    content = (
        f"Instagram（{account}）に新しいDMが届いています。\n\n"
        f"相手: @{handle}\n"
        f"内容: {preview[:500] or '(本文なし)'}"
    )
    sb.table("dan_proposals").insert({
        "user_id": user_id,
        "type": "action",
        "title": "InstagramにDMが届いています",
        "content": content,
        "status": "pending",
        "action_data": {
            "action": "instagram_dm_received",
            "channel": "instagram",
            "account": account,
            "handle": handle,
            "thread_id": thread["thread_id"],
            "detected_message_id": detected_id,
            "thread_url": f"https://www.instagram.com/direct/t/{thread['thread_id']}/",
        },
    }).execute()


def _notify_login_failed(user_id: str, account: str) -> None:
    """自力ログインに失敗した時だけ人に助けを求める（通常は自動で入れる）。"""
    from app.services.supabase_client import get_supabase_client
    sb = get_supabase_client().client
    existing = (
        sb.table("dan_proposals").select("id")
        .eq("user_id", user_id).eq("status", "pending")
        .contains("action_data", {"action": "instagram_login_failed", "account": account})
        .limit(1).execute().data or []
    )
    if existing:
        return  # 同じ依頼を溜めない
    sb.table("dan_proposals").insert({
        "user_id": user_id,
        "type": "action",
        "title": "Instagramに自力ログインできませんでした",
        "content": (
            f"Instagram（{account}）に自動でログインできず、DMの見張りを止めています。\n"
            "認証チャレンジ・パスワード変更・アカウント制限のいずれかの可能性があります。\n\n"
            f"手で入り直す場合: python scripts/ig_login_once.py {account}"
        ),
        "status": "pending",
        "action_data": {"action": "instagram_login_failed", "account": account,
                        "channel": "instagram"},
    }).execute()


# --------------------------------------------------------------------------
# 1アカウント分の巡回
# --------------------------------------------------------------------------

def _format_conversation(messages: List[Dict[str, Any]]) -> str:
    """会話の流れを、ダンが読める形のテキストにする。"""
    lines = []
    for m in messages:
        who = "自分" if m.get("is_from_me") else f"@{m.get('from')}"
        text = (m.get("text") or "").strip()
        if not text and m.get("item_type"):
            text = f"({m['item_type']})"
        lines.append(f"{who}: {text}")
    return "\n".join(lines)


async def _poll_account(user_id: str, account: str) -> None:
    from app.services.instagram_inbox import (
        ensure_logged_in, fetch_inbox_json, fetch_thread_json, open_session,
        parse_thread_messages, parse_threads,
    )

    from playwright.async_api import async_playwright

    new_items: List[Dict[str, Any]] = []

    from app.services.instagram_send import account_lock

    async with account_lock(account), async_playwright() as pw:
        context = None
        try:
            context, page = await open_session(account, pw)
            # ログインはダンが自力でやる（認証情報 + captcha + OTP）
            if not await ensure_logged_in(page, account, user_id):
                logger.warning("[ig] %s: 自力ログインに失敗", account)
                await asyncio.to_thread(_notify_login_failed, user_id, account)
                return

            data = await fetch_inbox_json(page)
            if data is None:
                await asyncio.to_thread(_notify_login_failed, user_id, account)
                return

            for thread in parse_threads(data):
                if len(new_items) >= MAX_THREADS_PER_CYCLE:
                    logger.info("[ig] %s: 上限%d件。残りは次回", account, MAX_THREADS_PER_CYCLE)
                    break
                if thread.get("is_from_me") or not thread.get("last_ts"):
                    continue  # 自分の送信が最後＝相手からの新着ではない
                if await asyncio.to_thread(
                    _already_seen, user_id, thread["thread_id"], thread["last_ts"]
                ):
                    continue

                handle = _counterpart(thread)
                route = (
                    await asyncio.to_thread(_find_route_for_handle, user_id, account, handle)
                    if handle else None
                )
                # 案件が特定できた相手なら、会話の流れも読んでダンに渡す
                conversation = ""
                if route:
                    detail = await fetch_thread_json(page, thread["thread_id"])
                    if detail:
                        conversation = _format_conversation(parse_thread_messages(detail))
                new_items.append({"thread": thread, "route": route, "handle": handle,
                                  "conversation": conversation})
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    logger.exception("[ig] context close failed")

    # ブラウザを閉じてから、保存・起動・通知を行う（ブラウザを長く掴まない）
    for item in new_items:
        thread, route, handle = item["thread"], item["route"], item["handle"]
        detected = await asyncio.to_thread(
            _record_detected, user_id, account, thread, item["conversation"]
        )
        if route and route.get("origin_room_id"):
            from app.services.inbound_wakeup import schedule_room_wakeup
            if schedule_room_wakeup(detected, route["origin_room_id"], reason="instagram_thread"):
                logger.info("[ig] %s: @%s の返信 → room=%s を起動", account, handle,
                            route["origin_room_id"][:8])
                continue
        await asyncio.to_thread(_create_proposal, user_id, account, thread, detected.get("id"))
        logger.info("[ig] %s: @%s からの新規DM → 通知タブ", account, handle)


async def _tick() -> None:
    from app.services.owner import resolve_owner_user_id
    user_id = resolve_owner_user_id()
    if not user_id:
        return
    accounts = await asyncio.to_thread(_watched_accounts, user_id)
    if not accounts:
        return  # 送信実績が無い＝見張る理由が無い
    for account in accounts:
        try:
            await _poll_account(user_id, account)
        except Exception:
            logger.exception("[ig] poll failed for account=%s", account)


async def poller_loop() -> None:
    logger.info("[ig] poller started (interval=%ss ±%d%%)", POLL_INTERVAL, int(JITTER_RATIO * 100))
    # 起動直後に走らせない（コア再起動のたびにアクセスが集中するのを避ける）
    await asyncio.sleep(_next_delay())
    while True:
        try:
            if _enabled():
                await _tick()
        except Exception:
            logger.exception("[ig] tick error")
        await asyncio.sleep(_next_delay())


def start_poller() -> Optional["asyncio.Task"]:
    global _started, _task
    if _started:
        return _task
    if not _enabled():
        logger.info("[ig] poller disabled (DAN_IG_POLLER_ENABLED)")
        return None
    _started = True
    _task = asyncio.create_task(poller_loop())
    return _task
