# -*- coding: utf-8 -*-
"""Background poller that fires Dan's watches (旧: deferred follow-ups).

Runs as a single asyncio task inside dan-core. Every POLL_INTERVAL it claims due
rows from pending_followups and acts by kind:

  - "at"    (one-shot): wake Dan in the room to check + report, then done.
  - "every" (recurring): wake Dan, then advance fire_at by interval_seconds.
  - "mail"  (condition): check IMAP; wake Dan only when matching mail arrived,
            then advance fire_at to the next check. The watch itself stays alive.

Wakes go through the normal process_message_cli path (NOT skip_save), resuming
the room's session so Dan remembers the surrounding context. This poller is the
machinery that lets a turn-based agent keep promises about the future — the
promise itself must live in the DB (the watch row), never only in Dan's head.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

POLL_INTERVAL = 20          # seconds between poll cycles
MAX_PER_CYCLE = 5           # cap fires per cycle so one busy cycle can't pile up
MAIL_ERROR_LIMIT = 30       # consecutive check failures before a mail watch gives up

_started = False
_task: Optional["asyncio.Task"] = None

_SYNTH_PROMPT = (
    "[システム自動再開 / scheduled follow-up]\n"
    "これはユーザーの新規メッセージではなく、あなた自身が予約した続報の自動トリガーです。\n\n"
    "あなたは少し前に、次のために続報を予約しました:\n"
    "「{note}」\n\n"
    "今、その作業の結果を実際に確認し、ユーザーに日本語でチャット報告してください。\n"
    "- 完了していれば、結果（成否・URL・確認した内容）を簡潔に報告する。\n"
    "- まだ完了していなければ、schedule_followup で短い遅延（60〜120秒）で再予約し、"
    "「まだ処理中です、もう少し待ってください」と一言だけ伝える。\n"
    "- ただし、確認した結果がこの部屋の直近の会話で既に報告・解決済みの内容と同じで、"
    "ユーザーに伝えるべき新情報が何もない場合は、本文を正確に「WATCH_NO_CHANGE」とだけ書くこと"
    "（システムが破棄し、ユーザーには何も表示されない。同じ内容の繰り返し報告は迷惑になる。"
    "余計な語を足すと破棄されず重複通知になってしまう）。\n"
    "余計な前置きや内部思考は出さず、ユーザーへの報告本文だけを書くこと。"
)

_NO_CHANGE_SENTINEL = "WATCH_NO_CHANGE"

_HANDOFF_PROMPT = (
    "[システム自動再開 / 別チャットからの引き継ぎ]\n"
    "これはユーザーの新規メッセージではありません。ユーザーが別のチャットで"
    "「この話は新しいチャットで話そう」と言ったため、あなた自身がこの新しいチャットを作りました。"
    "ここからはこの話題だけをこの部屋で続けます。\n\n"
    "元のチャットからの引き継ぎメモ:\n"
    "「{note}」\n\n"
    "今すぐこの部屋での一言目を書いてください:\n"
    "- まず「別のチャットから引き継いだ話題」であることが分かるよう、要点を2〜4行で短く再掲する。\n"
    "- 引き継ぎメモに『次にやること』が書かれていればそれを実行または着手し、"
    "質問が残っていればユーザーに聞く。\n"
    "- 元のチャットの本題（別の話題）には触れない。この部屋はこの話題専用。\n"
    "余計な前置きや内部思考は出さず、ユーザーへの本文だけを書くこと。"
)

_EVERY_PROMPT = (
    "[システム自動再開 / 定期見張り]\n"
    "これはユーザーの新規メッセージではなく、あなたが登録した定期見張りの定刻トリガーです。\n\n"
    "見張りの内容:\n「{note}」\n\n"
    "今、実際に実行・確認してください。\n"
    "- 見張りの内容が定期業務（資料作成・送信・振込準備など）なら、それを実際に実行する。"
    "不可逆な操作（送金の実行・外部への送信など）は、見張りの内容に「承認不要・実行して報告のみ」等の"
    "事前承認が明記されていればそのまま実行して結果を報告し、明記が無ければ準備まで進めて承認を求める。\n"
    "- 報告に値する変化・結果があれば、ユーザーに日本語で簡潔にチャット報告する。\n"
    "- 特筆すべき変化がなければ、本文を正確に「WATCH_NO_CHANGE」とだけ書くこと"
    "（システムが破棄し、ユーザーには何も表示されない。余計な語を足すと破棄されず通知になってしまう）。\n"
    "この見張りは継続中です。再登録は不要（二重登録になるので watch を新規作成しないこと）。"
    "もう不要だと判断できる明確な根拠がある場合のみ watch(action=\"cancel\") で止めてよい。"
)

_MAIL_PROMPT = (
    "[システム自動再開 / メール見張り]\n"
    "これはユーザーの新規メッセージではなく、あなたが登録したメール見張りが新着を検知した自動トリガーです。\n\n"
    "見張りの内容:\n「{note}」\n\n"
    "{mails}\n\n"
    "内容をユーザーに日本語で報告し、次に何をすべきか提案してください。"
    "期限が書かれていれば必ず日付を明示する。"
    "見張りの内容に事前承認（「承認不要・実行してよい」等）が明記されていない限り、"
    "ユーザーの承認なしに返信・送信・外部への働きかけをしてはいけない（報告と提案まで）。\n"
    "この見張りは継続中です。再登録は不要。"
)


def _resolve_project_id(room_id: str) -> Optional[str]:
    try:
        from app.services.supabase_client import get_supabase_client
        r = (
            get_supabase_client().client.table("projects")
            .select("id").eq("room_id", room_id).limit(1).execute()
        )
        return r.data[0]["id"] if r.data else None
    except Exception:
        return None


def _room_busy(room_id: str) -> bool:
    """True if a turn is already running for this room — defer the follow-up so
    we never interleave with the user's live turn."""
    try:
        from app.agent.streaming_session import get_session
        s = get_session(room_id)
        if s and s.is_turn_active():
            return True
    except Exception:
        pass
    try:
        from app.agent.cli_runner import is_cli_active
        if is_cli_active(room_id):
            return True
    except Exception:
        pass
    return False


async def _wake(room_id: str, user_id: str, content: str) -> None:
    """Drive one full Dan turn in the room with a synthetic system message."""
    from app.agent.cli_runner import process_message_cli

    project_id = _resolve_project_id(room_id)
    async for _ev in process_message_cli(
        room_id=room_id,
        user_id=user_id,
        content=content,
        project_id=project_id,
        run_id=None,
    ):
        pass  # the sink saves the report; we just drive the turn to completion


async def _fire_at(row: Dict[str, Any]) -> None:
    """One-shot wake ('at' / legacy plain-note followups)."""
    from app.services.followups import mark_status

    note = row.get("plain_note") or ""
    logger.info("[watch] at fires room=%s note=%r", row["room_id"][:8], note[:40])
    wake_start_iso = datetime.now(timezone.utc).isoformat()
    try:
        await _wake(row["room_id"], row.get("user_id") or "", _SYNTH_PROMPT.format(note=note))
        if await _discard_no_change_report(row["room_id"], wake_start_iso):
            logger.info("[watch] at no-change (silent) room=%s", row["room_id"][:8])
    except Exception as e:  # noqa: BLE001
        logger.error("[watch] at fire failed room=%s: %s", row["room_id"], e)
    # Done either way rather than risk an endless retry loop on a hard error.
    await asyncio.to_thread(mark_status, row["id"], "done")


async def _discard_no_change_report(room_id: str, since_iso: str) -> bool:
    """定期見張りの「変化なし」ターンを無言にする: 起床ターンが番兵文字列
    (WATCH_NO_CHANGE) だけを返した場合、その保存済みAIメッセージを削除して
    ユーザーに何も見せない。報告に値する内容はそのまま残る。"""
    def _do() -> bool:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
        rows = (
            sb.table("chat_messages").select("id,content")
            .eq("room_id", room_id).eq("sender_type", "ai")
            .gte("created_at", since_iso)
            .order("created_at", desc=True).limit(3).execute().data or []
        )
        deleted = False
        for m in rows:
            c = (m.get("content") or "").strip()
            if _NO_CHANGE_SENTINEL in c and len(c) <= 200:
                sb.table("chat_messages").delete().eq("id", m["id"]).execute()
                deleted = True
        if deleted:
            # 部屋一覧のプレビューは保存時に焼き込まれるコピーなので、消した
            # 番兵文言（WATCH_NO_CHANGE）が一覧に残り続ける。実在する最新
            # メッセージで書き直す（2026-08-26 実測）。
            from app.services.chat_service import refresh_room_preview_sync
            refresh_room_preview_sync(sb, room_id)
        return deleted

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:  # noqa: BLE001
        logger.warning("[watch] discard no-change failed room=%s: %s", room_id[:8], e)
        return False


async def _fire_every(row: Dict[str, Any]) -> None:
    from app.services.followups import mark_status, reschedule_watch

    note = row.get("plain_note") or ""
    spec = dict(row.get("spec") or {})
    interval = int(spec.get("interval_seconds") or 3600)
    now = datetime.now(timezone.utc)

    logger.info("[watch] every fires room=%s note=%r", row["room_id"][:8], note[:40])
    wake_start_iso = now.isoformat()
    try:
        await _wake(row["room_id"], row.get("user_id") or "", _EVERY_PROMPT.format(note=note))
        if await _discard_no_change_report(row["room_id"], wake_start_iso):
            logger.info("[watch] every no-change (silent) room=%s", row["room_id"][:8])
    except Exception as e:  # noqa: BLE001
        logger.error("[watch] every fire failed room=%s: %s", row["room_id"], e)

    until = spec.get("until")
    if until:
        try:
            if now >= datetime.fromisoformat(until.replace("Z", "+00:00")):
                await asyncio.to_thread(mark_status, row["id"], "done")
                return
        except (ValueError, TypeError):
            pass
    spec["fire_count"] = int(spec.get("fire_count") or 0) + 1
    from app.services.followups import next_calendar_fire
    next_at = next_calendar_fire(spec, now) or (now + timedelta(seconds=interval))
    await asyncio.to_thread(reschedule_watch, row["id"], "every", note, spec, next_at)


async def _fire_mail(row: Dict[str, Any]) -> None:
    from app.services.followups import mark_status, reschedule_watch
    from app.services.mail_watch import check_mail_watch, format_mails

    note = row.get("plain_note") or ""
    spec = dict(row.get("spec") or {})
    interval = int(spec.get("interval_seconds") or 600)
    now = datetime.now(timezone.utc)

    try:
        new_spec, mails = await asyncio.to_thread(check_mail_watch, spec)
        new_spec.pop("consecutive_errors", None)
    except Exception as e:  # noqa: BLE001
        errors = int(spec.get("consecutive_errors") or 0) + 1
        logger.error("[watch] mail check failed room=%s (%d/%d): %s",
                     row["room_id"][:8], errors, MAIL_ERROR_LIMIT, e)
        if errors >= MAIL_ERROR_LIMIT:
            # Persistent failure (e.g. revoked app password): surface it once,
            # then stop instead of erroring silently forever.
            try:
                await _wake(
                    row["room_id"], row.get("user_id") or "",
                    f"[システム自動再開 / メール見張りエラー] 見張り「{note}」のメール確認が"
                    f"{errors}回連続で失敗したため停止しました。最後のエラー: {e}。"
                    "ユーザーに報告し、原因（パスワード失効など）の対処を提案してください。")
            except Exception:  # noqa: BLE001
                pass
            await asyncio.to_thread(mark_status, row["id"], "done")
            return
        spec["consecutive_errors"] = errors
        await asyncio.to_thread(
            reschedule_watch, row["id"], "mail", note, spec, now + timedelta(seconds=interval))
        return

    if mails:
        logger.info("[watch] mail hit room=%s count=%d", row["room_id"][:8], len(mails))
        new_spec["fire_count"] = int(new_spec.get("fire_count") or 0) + len(mails)
        try:
            await _wake(
                row["room_id"], row.get("user_id") or "",
                _MAIL_PROMPT.format(note=note, mails=format_mails(mails)))
        except Exception as e:  # noqa: BLE001
            logger.error("[watch] mail wake failed room=%s: %s", row["room_id"], e)
    await asyncio.to_thread(
        reschedule_watch, row["id"], "mail", note, new_spec, now + timedelta(seconds=interval))


async def _fire_handoff(row: Dict[str, Any]) -> None:
    """One-shot wake in a freshly split room: Dan speaks first with the
    handoff memo. No no-change discard here — the first message in the new
    room is always new information."""
    from app.services.followups import mark_status

    note = row.get("plain_note") or ""
    logger.info("[watch] handoff fires room=%s note=%r", row["room_id"][:8], note[:40])
    try:
        await _wake(row["room_id"], row.get("user_id") or "", _HANDOFF_PROMPT.format(note=note))
    except Exception as e:  # noqa: BLE001
        logger.error("[watch] handoff fire failed room=%s: %s", row["room_id"], e)
    await asyncio.to_thread(mark_status, row["id"], "done")


async def _fire(row: Dict[str, Any]) -> None:
    from app.services.followups import decode_watch_row

    d = decode_watch_row(row)
    kind = d.get("kind") or "at"
    if kind == "mail":
        await _fire_mail(d)
    elif kind == "every":
        await _fire_every(d)
    elif kind == "handoff":
        await _fire_handoff(d)
    else:
        await _fire_at(d)


async def _tick() -> None:
    from app.services.followups import claim_due_followups, mark_status

    rows = await asyncio.to_thread(claim_due_followups, MAX_PER_CYCLE)
    for row in rows:
        if _room_busy(row["room_id"]):
            # Put it back; retry on a later cycle when the room is idle.
            await asyncio.to_thread(mark_status, row["id"], "pending")
            continue
        await _fire(row)


async def poller_loop() -> None:
    logger.info("[watch] poller started (interval=%ss)", POLL_INTERVAL)
    while True:
        try:
            await _tick()
        except Exception as e:  # noqa: BLE001
            logger.error("[watch] tick error: %s", e)
        await asyncio.sleep(POLL_INTERVAL)


def start_poller() -> Optional["asyncio.Task"]:
    """Start the poller once. Safe to call from a FastAPI lifespan startup."""
    global _started, _task
    if _started:
        return _task
    _started = True
    _task = asyncio.create_task(poller_loop())
    return _task
