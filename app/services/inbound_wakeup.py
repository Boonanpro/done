# -*- coding: utf-8 -*-
"""外部着信をルームに直接届け、ダンのターンを起動する(wake)。

email_poller の照合でルームが確定した受信（帳簿ヘッダ=強一致 / LLM内容判定=existing）
について、通知タブに提案を置く代わりに、そのルームで process_message_cli を起動して
ダン自身に「進展の報告と次アクションの提案」をさせる。二重表示を避けるため、
wake できた受信は dan_proposals を作らない（wake 失敗時のみ通知にフォールバック）。

規律:
- ルームでターン実行中なら idle になるまで待って発火（followup_poller と同じ）。
- 待機がタイムアウトしたら、取りこぼさないよう dan_proposals にフォールバック。
- wake されたダンは報告と提案まで。ユーザー承認なしの外部送信はプロンプトで禁止。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

BUSY_RETRY_INTERVAL = 20      # ルームが busy の時の再確認間隔(秒)
BUSY_MAX_WAIT = 15 * 60       # これ以上待ったら通知タブにフォールバック(秒)

# fire-and-forget タスクの GC 防止
_tasks: Set["asyncio.Task"] = set()

_WAKE_PROMPT = (
    "[外部連絡の自動検知 / inbound {channel}]\n"
    "これはユーザーの発言ではありません。このルームの案件に関係する外部からの連絡を"
    "システムが検知し、あなたを自動起動しました。\n\n"
    "--- 受信した連絡 ---\n"
    "差出人: {sender}\n"
    "件名: {subject}\n"
    "受信日時: {date}\n"
    "メッセージID: {message_id}\n"
    "{extra}"
    "本文:\n{body}\n"
    "--- ここまで ---\n"
    "(振り分け理由: {reason})\n\n"
    "やること:\n"
    "1. このルームのこれまでの経緯を踏まえ、この連絡による進展・要点を短くユーザーに報告する。\n"
    "2. 次のアクションを具体的に提案する。返信すべき内容なら、返信文を "
    "{compose_hint} で送信案カードとして出す（件名不要・本文をチャットに書かない）。"
    "ユーザーはカード上で直して送信できる。\n"
    "3. {send_policy}\n"
    "余計な前置きや内部思考は書かず、ユーザーへの報告と提案だけを書くこと。"
)

# collab（外部窓口）専用: 対応の主戦場はコミュニケーションタブ側。
# この部屋（origin ルーム）には文脈共有のための短い作業ログだけを残す。
_WAKE_PROMPT_COLLAB = (
    "[外部窓口の着信 / collab]\n"
    "これはユーザーの発言ではありません。この部屋に紐付いた外部窓口（コラボチャット）に "
    "{sender} さんからメッセージが届き、あなたが自動起動されました。\n\n"
    "--- 受信メッセージ ---\n{body}\n--- ここまで ---\n"
    "{extra}\n"
    "やること:\n"
    "1. 必要な作業（成果物の修正・調査・準備など）があれば、このターン内で実際に行う。\n"
    "2. 返信すべき内容なら {compose_hint} で送信案カードを出す。"
    "カードは窓口のオーナー画面（コミュニケーションタブ）にも表示され、ユーザーはそこで直して送信できる。\n"
    "   ★返信の文体: これは**チャット**であってメールではない。宛名（「◯◯様」「◯◯院長」）・"
    "「お世話になっております」等の定型挨拶・締めの「よろしくお願いいたします」・署名は書かない。"
    "会話の流れに自然に続く話し方で、相手のトーンと長さに合わせて簡潔に（通常2〜6行。"
    "確認事項が多い時だけ箇条書きで長くてよい）。毎回同じ型で書き始めない。\n"
    "3. {send_policy}\n"
    "4. この部屋への出力は【短い作業ログ1〜3行だけ】にし、必ず「窓口ログ:」で書き始める"
    "（例:「窓口ログ: {sender}さんから料金改定の依頼 → HPに反映済み、返信案を窓口に出しました」）。"
    "この書き出しだと画面では折り畳みの控えめな行として表示される。"
    "長い報告・受信本文の引用・返信本文の繰り返し・前置きは書かない。"
    "ユーザーは通知を見てコミュニケーションタブ側で対応する。詳細はそちらの会話とカードに残っている。"
)

_DEFAULT_SEND_POLICY = (
    "ユーザーの承認なしに送信（compose_message の send）を実行してはいけない。今回は報告と送信案まで。"
)


def _send_policy(detected_message: Dict[str, Any]) -> str:
    """窓口ごとの運用方針（自動返信の許可範囲）。collab の ai_assist_config を
    metadata 経由で受け取る。既定は全件承認必須。"""
    md = detected_message.get("metadata") or {}
    if str(md.get("autonomy") or "").lower() == "auto":
        guidance = (md.get("auto_guidance") or "").strip() or "軽い受領確認・お礼・既に確定した事項の共有のみ"
        return (
            f"この窓口はユーザーが一部の自動返信を許可している。許可範囲:「{guidance}」。"
            "この範囲に明確に収まる返信だけは、送信案カードを出した上で同じターン内に send まで実行してよい"
            "（送信の事実は部屋に記録され、ユーザーは後から確認できる）。"
            "範囲外の内容・新しい約束・金額/納期/仕様の判断が要るものは send せず、"
            "報告と送信案カードまでで止めてユーザーの確認を待て。迷ったら承認待ちに倒せ。"
        )
    return _DEFAULT_SEND_POLICY


def _extra_lines(detected_message: Dict[str, Any]) -> str:
    """SNS 受信の返信に必要な識別子（thread_id / account / 投稿URL 等）を列挙する。"""
    md = detected_message.get("metadata") or {}
    si = detected_message.get("sender_info") or {}
    parts = []
    if md.get("thread_id"):
        parts.append(f"thread_id: {md['thread_id']}（返信は reply_to_thread_id に渡す）")
    acc = md.get("account") or si.get("account")
    if acc:
        parts.append(f"account: {acc}（返信は from_account に渡す）")
    if si.get("handle"):
        parts.append(f"相手ハンドル: @{si['handle']}（to に渡す）")
    if md.get("post_url"):
        parts.append(f"投稿URL: {md['post_url']}（reply_to_post_url）")
    if md.get("comment_id"):
        parts.append(f"comment_id: {md['comment_id']}（reply_to_comment_id）")
    if md.get("collab_room_id"):
        parts.append(f"collab_room_id: {md['collab_room_id']}（返信は compose_message の collab_room_id に渡す）")
    return "".join(f"{p}\n" for p in parts)


def _compose_hint(detected_message: Dict[str, Any]) -> str:
    """チャネル別に、返信で compose_message に渡すべき引数の例を作る。"""
    src = str(detected_message.get("source") or "")
    md = detected_message.get("metadata") or {}
    si = detected_message.get("sender_info") or {}
    if src == "instagram":
        return (
            f'compose_message(action="propose", channel="instagram_dm", to="{si.get("handle") or ""}", '
            f'from_account="{md.get("account") or si.get("account") or ""}", '
            f'reply_to_thread_id="{md.get("thread_id") or ""}", body=...)'
        )
    if src == "collab":
        return (
            f'compose_message(action="propose", channel="collab", to="{si.get("from") or "ゲスト"}", '
            f'collab_room_id="{md.get("collab_room_id") or ""}", body=...)'
            "（件名不要。送信すると相手のコラボチャットに直接届く）"
        )
    mid = md.get("message_id") or detected_message.get("source_id") or ""
    return (
        f'compose_message(action="propose", channel="email", reply_to_message_id="{mid}", '
        f'reply_to_subject="{detected_message.get("subject") or ""}", body=...)'
    )


def _build_prompt(detected_message: Dict[str, Any], reason: str) -> str:
    sender_info = detected_message.get("sender_info") or {}
    body = (detected_message.get("content") or "").strip()
    if len(body) > 2000:
        body = body[:2000] + "\n...(以下省略)"
    if str(detected_message.get("source") or "") == "collab":
        return _WAKE_PROMPT_COLLAB.format(
            sender=sender_info.get("from") or "ゲスト",
            body=body or "(本文なし)",
            extra=_extra_lines(detected_message),
            compose_hint=_compose_hint(detected_message),
            send_policy=_send_policy(detected_message),
        )
    return _WAKE_PROMPT.format(
        channel=detected_message.get("source") or "message",
        sender=sender_info.get("from") or sender_info.get("email") or "不明",
        subject=detected_message.get("subject") or "(件名なし)",
        message_id=(detected_message.get("metadata") or {}).get("message_id") or detected_message.get("source_id") or "",
        extra=_extra_lines(detected_message),
        compose_hint=_compose_hint(detected_message),
        send_policy=_send_policy(detected_message),
        date=sender_info.get("date") or "不明",
        body=body or "(本文なし)",
        reason=reason,
    )


def _fallback_proposal(detected_message: Dict[str, Any], room_id: str, reason: str) -> None:
    """wake できなかった受信を通知タブに落とす（取りこぼし防止）。同期実行。"""
    from app.services.supabase_client import get_supabase_client

    sender_info = detected_message.get("sender_info") or {}
    sender = sender_info.get("from") or sender_info.get("email") or "不明"
    subject = detected_message.get("subject") or "(件名なし)"
    body = (detected_message.get("content") or "").strip()[:1200]
    content = (
        f"このチャットの案件に関係する連絡を検知しましたが、ルームが混雑していたため通知でお知らせします。\n\n"
        f"送信者: {sender}\n件名: {subject}\n\n--- 本文 ---\n{body}"
    )
    get_supabase_client().client.table("dan_proposals").insert({
        "user_id": detected_message["user_id"],
        "type": "action",
        "title": "確認してください",
        "content": content,
        "source_room_id": room_id,
        "status": "pending",
        "action_data": {
            "action": "external_reply_detected",
            "detected_message_id": detected_message.get("id"),
            "channel": detected_message.get("source"),
            "routing_reason": reason,
            "fallback": "wakeup_busy_timeout",
        },
    }).execute()


async def _wake_task(detected_message: Dict[str, Any], room_id: str, reason: str) -> None:
    # followup_poller と同じ busy 判定/プロジェクト解決を使う（規律を揃える）
    from app.services.followup_poller import _resolve_project_id, _room_busy

    waited = 0
    while _room_busy(room_id):
        if waited >= BUSY_MAX_WAIT:
            logger.warning("[inbound-wake] room=%s busy for %ss, falling back to proposal", room_id[:8], waited)
            await asyncio.to_thread(_fallback_proposal, detected_message, room_id, reason)
            return
        await asyncio.sleep(BUSY_RETRY_INTERVAL)
        waited += BUSY_RETRY_INTERVAL

    from app.agent.cli_runner import process_message_cli

    prompt = _build_prompt(detected_message, reason)
    user_id = detected_message.get("user_id") or ""
    project_id = _resolve_project_id(room_id)
    logger.info("[inbound-wake] firing room=%s msg=%s reason=%s", room_id[:8], detected_message.get("id"), reason)
    try:
        async for _ev in process_message_cli(
            room_id=room_id,
            user_id=user_id,
            content=prompt,
            project_id=project_id,
            run_id=None,
        ):
            pass  # sink が報告を保存する。ここではターン完走を駆動するだけ
    except Exception:
        logger.exception("[inbound-wake] turn failed room=%s msg=%s", room_id, detected_message.get("id"))
        try:
            await asyncio.to_thread(_fallback_proposal, detected_message, room_id, reason)
        except Exception:
            logger.exception("[inbound-wake] fallback proposal also failed msg=%s", detected_message.get("id"))


def schedule_room_wakeup(detected_message: Dict[str, Any], room_id: str, *, reason: str) -> bool:
    """該当ルームでダンを起動するタスクを予約する。予約できたら True。

    False の場合、呼び出し側は従来どおり dan_proposals(通知タブ)を作ること。
    """
    if not room_id or not detected_message.get("user_id"):
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("[inbound-wake] no running loop; cannot schedule wake for msg=%s", detected_message.get("id"))
        return False
    task = loop.create_task(_wake_task(detected_message, room_id, reason))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True
