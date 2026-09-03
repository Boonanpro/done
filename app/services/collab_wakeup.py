# -*- coding: utf-8 -*-
"""コラボ窓口（外部チャット）の着信をまとめてダンに届けるアグリゲータ。

1メッセージ=1起動をやめ、窓口ごとに1本のウェイターが着信を畳む:

- **デバウンス**: 最後の着信から QUIET_SECONDS 静かになるまで起動を遅らせ、
  連投（間隔の有無を問わず）を1回の起動にまとめる。
- **まとめ読み**: 起動時は「未処理のゲストメッセージ全部」をプロンプトに渡す。
  未処理判定は (a) 最後の自分側発言より後のゲスト発言 かつ (b) 処理済みマーカー
  （collab_rooms.ai_assist_config.last_handled_message_at）より後、の両方。
- **続き処理**: ターン実行中に届いた分は同じウェイターが次のバッチとして処理する
  （「やっぱりさっきの無しで」が前のカードを知った上で扱われる）。
- **永続性**: マーカーはDBにあるので、コア再起動でメモリが飛んでも次の着信時に
  未処理分をまとめて回収できる。

busy 規律・フォールバックは inbound_wakeup と同じ:
origin ルームが混雑なら待つ（待機中の新着もバッチに合流）、限界超えは通知タブへ。
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

QUIET_SECONDS = 60            # 最後の着信からこれだけ静かになったら起動（連投の畳み込み）
BUSY_RETRY_INTERVAL = 20
BUSY_MAX_WAIT = 15 * 60

# collab_room_id -> {"last_activity": monotonic, "task": asyncio.Task}
_states: Dict[str, Dict[str, Any]] = {}
_tasks: Set["asyncio.Task"] = set()


def schedule_collab_wakeup(collab_room_id: str) -> bool:
    """着信を通知する。既にウェイターが居ればデバウンス時計を巻き直すだけ。"""
    if not collab_room_id:
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("[collab-wake] no running loop; cannot schedule for %s", collab_room_id[:8])
        return False
    # 着信の瞬間から「考え中...」を点灯する（デバウンス待ちの間も含めて）。
    # 消灯はウェイター終了時（_waiter の finally）。
    t = loop.create_task(_notify_status(collab_room_id, "thinking"))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)

    state = _states.get(collab_room_id)
    if state and state.get("task") and not state["task"].done():
        state["last_activity"] = time.monotonic()
        return True
    task = loop.create_task(_waiter(collab_room_id))
    _states[collab_room_id] = {"last_activity": time.monotonic(), "task": task}
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True


async def _waiter(collab_room_id: str) -> None:
    from app.services.collab_service import CollabService

    state = _states[collab_room_id]
    try:
        while True:
            # 1) デバウンス: 最終着信から QUIET_SECONDS 経過するまで待つ
            while True:
                elapsed = time.monotonic() - state["last_activity"]
                if elapsed >= QUIET_SECONDS:
                    break
                await asyncio.sleep(QUIET_SECONDS - elapsed + 0.5)

            svc = CollabService()
            room = await svc.get_room(collab_room_id)
            if not room or not room.get("origin_chat_room_id"):
                return
            origin_room_id = room["origin_chat_room_id"]

            batch = await _fetch_unhandled(svc, room)
            if not batch:
                return

            # 対応開始。オーナー画面に「ダンが対応中…」を点灯
            await _notify_status(collab_room_id, "thinking")
            try:
                # 2) origin ルームの busy 待ち（待機中の新着は再取得でバッチに合流）
                from app.services.followup_poller import _resolve_project_id, _room_busy

                waited = 0
                while _room_busy(origin_room_id):
                    if waited >= BUSY_MAX_WAIT:
                        logger.warning("[collab-wake] origin=%s busy %ss; falling back to proposal",
                                       origin_room_id[:8], waited)
                        await _fallback_proposal(svc, collab_room_id, batch)
                        await _mark_handled(svc, room, batch)
                        return
                    await asyncio.sleep(BUSY_RETRY_INTERVAL)
                    waited += BUSY_RETRY_INTERVAL
                    batch = await _fetch_unhandled(svc, room) or batch

                # 3) ターン実行
                from app.agent.cli_runner import process_message_cli

                prompt = await _build_prompt(svc, room, batch)
                project_id = _resolve_project_id(origin_room_id)
                logger.info("[collab-wake] firing origin=%s collab=%s batch=%d",
                            origin_room_id[:8], collab_room_id[:8], len(batch))
                try:
                    async for _ev in process_message_cli(
                        room_id=origin_room_id,
                        user_id=room["owner_id"],
                        content=prompt,
                        project_id=project_id,
                        run_id=None,
                    ):
                        pass
                    await _mark_handled(svc, room, batch)
                except Exception:
                    logger.exception("[collab-wake] turn failed collab=%s", collab_room_id)
                    try:
                        await _fallback_proposal(svc, collab_room_id, batch)
                        await _mark_handled(svc, room, batch)
                    except Exception:
                        logger.exception("[collab-wake] fallback also failed collab=%s", collab_room_id)
                    return
            finally:
                await _notify_status(collab_room_id, "done")

            # 4) ターン中の新着があれば、デバウンスからやり直して次のバッチへ
            room = await svc.get_room(collab_room_id) or room
            more = await _fetch_unhandled(svc, room)
            if not more:
                return
            state["last_activity"] = time.monotonic()
    finally:
        _states.pop(collab_room_id, None)
        # どの経路で終了しても消灯する（schedule 時に点灯済みのため）
        await _notify_status(collab_room_id, "done")


def schedule_owner_instruction(collab_room_id: str, content: str,
                               thread_root: str = None, public: bool = False) -> bool:
    """ユーザーが窓口画面で送ったメッセージを origin ルームのダンに即時に届ける。
    デバウンスしない（本人との会話なので即応）。

    thread_root: 相談スレッドの親メッセージID（私的返信の続き用）。
    public: True なら公開の場での発言（ダン宛てかはダンが判断し、宛てられていれば
    公開の場で直接返答する）。
    """
    if not collab_room_id or not (content or "").strip():
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("[collab-wake] no running loop for owner instruction %s", collab_room_id[:8])
        return False
    task = loop.create_task(_owner_instruction_turn(collab_room_id, content.strip(), thread_root, public))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True


async def _owner_instruction_turn(collab_room_id: str, content: str,
                                  thread_root: str = None, public: bool = False) -> None:
    from app.services.collab_service import CollabService

    svc = CollabService()
    room = await svc.get_room(collab_room_id)
    if not room or not room.get("origin_chat_room_id"):
        return
    origin_room_id = room["origin_chat_room_id"]

    # ユーザーが発言した直後から「考え中...」を点灯（busy待ち中も点けたまま）
    await _notify_status(collab_room_id, "thinking")
    try:
        await _owner_instruction_turn_inner(svc, room, collab_room_id, origin_room_id,
                                            content, thread_root, public)
    finally:
        await _notify_status(collab_room_id, "done")


async def _owner_instruction_turn_inner(svc, room: dict, collab_room_id: str,
                                        origin_room_id: str, content: str,
                                        thread_root: str = None, public: bool = False) -> None:
    from app.services.followup_poller import _resolve_project_id, _room_busy

    waited = 0
    while _room_busy(origin_room_id):
        if waited >= BUSY_MAX_WAIT:
            logger.warning("[collab-wake] owner instruction dropped (busy) collab=%s", collab_room_id[:8])
            return
        await asyncio.sleep(BUSY_RETRY_INTERVAL)
        waited += BUSY_RETRY_INTERVAL

    # 窓口の直近の流れ（秘匿含む: 本人向けなので相談・私的指示も見せる）
    recent = await svc.get_messages(collab_room_id, limit=12)
    ctx_lines = []
    for m in recent:
        vis = (m.get("metadata") or {}).get("visibility")
        if vis == "guest_only":
            continue
        st = m.get("sender_type")
        who = {"guest": f"相手({m.get('sender_name')})", "owner": "ユーザー",
               "dan_owner": "あなた(ダン)"}.get(st, st)
        if vis == "owner_only":
            who += "・相手に非表示"
        ctx_lines.append(f"【{who}】{_text_for_dan(m)[:300]}")
    ctx = "\n".join(ctx_lines[-10:])

    if public:
        prompt = (
            f"[窓口でのユーザーの公開発言 / collab]\n"
            f"ユーザー（雇い主）が外部窓口「{room.get('title')}」の**公開の場**（相手にも見える）で発言しました。\n\n"
            f"## 窓口の直近の流れ\n{ctx}\n\n"
            f"## ユーザーの発言（公開）\n{content}\n\n"
            f"## 判断と出力先\n"
            f"- あなたに向けられた発言・質問・依頼なら: 必要な作業をこのターン内で行い、"
            f"collab_thread(action=\"say\", collab_room_id=\"{collab_room_id}\", body=...) で"
            f"**公開の場に直接返答する**（承認不要・相手にも見える。公開で聞かれたのに黙ると"
            f"ユーザーが無視された形になるので、宛てられたら必ず返す）。\n"
            f"- 相手宛ての発言や人間同士の会話なら: 何も出さない（リアクションも不要）。\n"
            f"- 相手への改まった連絡文が別途必要な場合のみ compose_message のカードを使う。\n"
            f"返信の文体はチャット準拠（宛名・定型挨拶・署名なし・復唱しない・簡潔に）。\n"
            f"この部屋への出力は「窓口ログ:」で始まる1行だけ。"
        )
    else:
        prompt = (
            f"[窓口でのユーザー指示 / collab]\n"
            f"ユーザー（雇い主）が外部窓口「{room.get('title')}」の画面で、あなた宛に（相手に見えない形で）返答/指示しました。\n\n"
            f"## 窓口の直近の流れ\n{ctx}\n\n"
            f"## ユーザーの発言\n{content}\n\n"
            f"## 出力先\n"
            f"あなたが出した相談への返答なら、その方針に従って作業・返信案"
            f"（compose_message(action=\"propose\", channel=\"collab\", collab_room_id=\"{collab_room_id}\", ...））"
            f"・相手への確認を進める。新たな指示ならそれに従う。さらに確認や報告が要る時は "
            f"collab_thread(action=\"consult\", collab_room_id=\"{collab_room_id}\""
            + (f", reply_to_message_id=\"{thread_root}\"" if thread_root else "")
            + ", body=...) で返す（前置きなしでいきなり本題"
            + ("。reply_to_message_id 付きなら同じ相談スレッドの続きとして表示される。新しいバブルを作らないこと" if thread_root else "")
            + "）。"
            f"人間にしかできない一歩が必要な時は、最短の導線（開くだけのURL等）にして相談に添える。\n"
            f"返信の文体はチャット準拠（宛名・定型挨拶・署名なし・復唱しない・簡潔に）。\n"
            f"この部屋への出力は「窓口ログ:」で始まる1〜3行だけ。"
        )
    project_id = _resolve_project_id(origin_room_id)
    logger.info("[collab-wake] owner instruction firing origin=%s collab=%s",
                origin_room_id[:8], collab_room_id[:8])
    try:
        from app.agent.cli_runner import process_message_cli
        async for _ev in process_message_cli(
            room_id=origin_room_id,
            user_id=room["owner_id"],
            content=prompt,
            project_id=project_id,
            run_id=None,
        ):
            pass
    except Exception:
        logger.exception("[collab-wake] owner instruction turn failed collab=%s", collab_room_id)


async def _notify_status(collab_room_id: str, status: str) -> None:
    """オーナー画面の「ダンが対応中…」インジケーターを点灯/消灯する（best-effort）。"""
    import os
    import httpx
    port = os.environ.get("DAN_SANDBOX_PORT", "8000")
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(
                f"http://127.0.0.1:{port}/api/v1/collab/internal/dan-status",
                json={"room_id": collab_room_id, "status": status},
            )
    except Exception:
        pass


async def _fetch_unhandled(svc, room: dict) -> List[dict]:
    """未処理のゲスト発言 = 「最後の自分側発言より後」かつ「マーカーより後」。

    guest_only（ゲストの @ダン 私的相談）は対象外。
    """
    messages = await svc.get_messages(room["id"], limit=40)
    cfg = room.get("ai_assist_config") or {}
    marker = cfg.get("last_handled_message_at")

    # 最後の自分側（owner / dan_owner の全体公開）発言の位置。
    # owner_only（相談・ダンへの私的指示）は相手に見えていないので基準にしない
    # （基準にすると、その裏で届いていたゲスト発言が未処理のまま漏れる）。
    last_own_at: Optional[str] = None
    for m in messages:
        vis = (m.get("metadata") or {}).get("visibility")
        if m.get("sender_type") in ("owner", "dan_owner") and vis not in ("guest_only", "owner_only"):
            last_own_at = m.get("created_at")

    batch: List[dict] = []
    for m in messages:
        if m.get("sender_type") != "guest":
            continue
        if (m.get("metadata") or {}).get("visibility") == "guest_only":
            continue
        created = m.get("created_at") or ""
        if last_own_at and created <= last_own_at:
            continue
        if marker and created <= marker:
            continue
        batch.append(m)
    return batch


async def _mark_handled(svc, room: dict, batch: List[dict]) -> None:
    if not batch:
        return
    newest = max((m.get("created_at") or "") for m in batch)
    cfg = dict(room.get("ai_assist_config") or {})
    cfg["last_handled_message_at"] = newest
    try:
        await svc._retry("mark_handled",
            lambda: svc.supabase.table("collab_rooms")
                .update({"ai_assist_config": cfg})
                .eq("id", room["id"]).execute())
        room["ai_assist_config"] = cfg
    except Exception:
        logger.warning("[collab-wake] mark_handled failed room=%s", room["id"], exc_info=True)


_COLLAB_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "collab"


def _text_for_dan(m: dict) -> str:
    """本文＋添付。画像はローカルパスで渡す（ダンが Read で実際に見られる）。
    動画・その他はURLのまま（配信は sandbox の /api/v1/collab/files/...）。"""
    md = m.get("metadata") or {}
    files = md.get("files") or ([md["file"]] if md.get("file") else [])
    body = (m.get("content") or "").strip()
    if not files:
        return body
    # 添付だけのメッセージは本文=ファイル名なので本文を省く
    names = {f.get("name") for f in files}
    if body in names or body in ("", "画像", "動画"):
        body = ""
    import os
    sandbox_port = os.environ.get("DAN_SANDBOX_PORT", "8000")
    lines = [body] if body else []
    for f in files:
        url = f.get("url") or ""
        kind = f.get("type") or ""
        name = f.get("name") or "file"
        local = None
        if url.startswith("/api/v1/collab/files/"):
            rel = url[len("/api/v1/collab/files/"):]
            cand = _COLLAB_UPLOAD_DIR / rel
            if cand.exists():
                local = cand.as_posix()
        if kind.startswith("image/") and local:
            lines.append(f"[添付画像: {local}]")
        elif kind.startswith("video/"):
            lines.append(f"[添付動画: {name} (http://127.0.0.1:{sandbox_port}{url})]")
        else:
            lines.append(f"[添付ファイル: {name} ({local or url})]")
    return "\n".join(lines)


async def _fallback_proposal(svc, collab_room_id: str, batch: List[dict]) -> None:
    """wake できない時は通知タブへ（複数件は1つの通知にまとめる）。"""
    joined = "\n---\n".join((m.get("content") or "").strip() for m in batch)[:2400]
    combined = {
        "id": batch[-1].get("id"),
        "sender_type": "guest",
        "sender_name": batch[-1].get("sender_name") or "ゲスト",
        "content": joined,
    }
    await svc.notify_origin_chat_of_guest_message(collab_room_id, combined)


def _policy_text(room: dict) -> str:
    from app.services.inbound_wakeup import _send_policy
    return _send_policy({"metadata": {
        "autonomy": (room.get("ai_assist_config") or {}).get("autonomy"),
        "auto_guidance": (room.get("ai_assist_config") or {}).get("auto_guidance"),
    }})


async def _build_prompt(svc, room: dict, batch: List[dict]) -> str:
    collab_room_id = room["id"]
    sender = batch[-1].get("sender_name") or "ゲスト"

    # 会話の流れ（直近・秘匿以外）
    recent = await svc.get_messages(collab_room_id, limit=14)
    batch_ids = {m.get("id") for m in batch}
    ctx_lines = []
    for m in recent:
        if m.get("id") in batch_ids:
            continue
        vis = (m.get("metadata") or {}).get("visibility")
        if vis in ("guest_only", "owner_only"):
            continue
        st = m.get("sender_type")
        who = {"guest": f"相手({m.get('sender_name')})", "owner": "あなた側(ユーザー本人が送信)",
               "dan_owner": "あなた側(ダンが送信)"}.get(st, st)
        ctx_lines.append(f"【{who}】{_text_for_dan(m)[:300]}")
    ctx = "\n".join(ctx_lines[-10:]) or "(まだ会話はありません)"

    new_lines = []
    for i, m in enumerate(batch, 1):
        t = (m.get("created_at") or "")[11:16]
        new_lines.append(f"{i}. [{t}] (message_id: {m.get('id')}) {_text_for_dan(m)}")
    news = "\n".join(new_lines)

    plural = f"新着{len(batch)}件をまとめて読み、全体として" if len(batch) > 1 else "この内容に"

    return (
        f"[外部窓口の着信 / collab]\n"
        f"これはユーザーの発言ではありません。この部屋に紐付いた外部窓口（コラボチャット）に "
        f"{sender} さんからメッセージが届きました。\n\n"
        f"## 人物\n"
        f"- ユーザー＝雇い主（この部屋の主。相談・承認の相手）\n"
        f"- {sender} さん＝外部の相手（クライアント。窓口の向こう側）\n\n"
        f"## これまでの会話（窓口）\n{ctx}\n\n"
        f"## 新着メッセージ（未対応 {len(batch)}件）\n{news}\n\n"
        f"## この窓口での出力先（通常のチャット返信と違うのはここだけ）\n"
        f"{plural}内容に応じて:\n"
        f"- **軽微で明確な依頼**（誤字修正・表記変更・事実の質問など）→ このターン内で作業し、"
        f"結果の返信案を compose_message(action=\"propose\", channel=\"collab\", "
        f"collab_room_id=\"{collab_room_id}\", to=\"{sender}\", body=...) でカード化"
        f"（ユーザーが窓口画面で直して送信できる）。\n"
        f"- **ユーザーの判断が要る内容**（費用や納期の約束・デザインやブランドの方針・大きな仕様変更・"
        f"過去の指示との矛盾など）→ 作業せず "
        f"collab_thread(action=\"consult\", collab_room_id=\"{collab_room_id}\", body=\"状況の要約＋提案＋質問\") "
        f"で相談（相手には見えない。前置きなしで本題から）。"
        f"人間にしかできない一歩（アカウントの同意画面を押す等）が必要な時は、"
        f"その一歩を最短にした導線（開くだけのURL等）を相談に添える。\n"
        f"- **あなた宛て・あなたの作業への反応**（お礼・了解など）で返信不要 → "
        f"collab_thread(action=\"react\", collab_room_id=\"{collab_room_id}\", message_id=\"<該当の message_id>\") "
        f"で 🙏 リアクションのみ（相手に通知は飛ばない・承認不要）。\n"
        f"- **ユーザーと{sender}さんの人間同士の会話**（雑談・二人の間の約束や話題）→ 何も出さない。"
        f"リアクションも付けない。\n\n"
        f"## 返信の文体（重要）\n"
        f"これは**チャット**であってメールではない。宛名（「◯◯様」「◯◯院長」）・「お世話になっております」"
        f"等の定型挨拶・締めの「よろしくお願いいたします」・署名は書かない。会話の流れに自然に続く話し方で、"
        f"相手のトーンと長さに合わせて簡潔に（通常2〜6行。確認事項が多い時だけ箇条書きで長くてよい）。"
        f"連投にはカード**1枚**でまとめて応じる（1通ごとに返さない）。\n"
        f"**相手の依頼内容を復唱しない**。依頼どおりにやったなら「反映しました、ご確認ください」程度で足りる。"
        f"書いてよいのは、相手がまだ知らないこと（相違点・気を利かせた追加・確認したいこと）だけ。"
        f"依頼と同じ内容の羅列（日付・金額・文言の繰り返し）はオウム返しであり禁止。"
        f"ただし依頼と**違う形**にした部分だけは明示する。\n\n"
        f"## 送信の規律\n{_policy_text(room)}\n"
        f"（🙏リアクション（collab_thread の react）はメッセージ送信ではないので承認不要）\n\n"
        f"## この部屋への出力\n"
        f"「窓口ログ:」で始まる1〜3行の作業ログだけ。長い報告・本文引用・前置きは書かない。"
        f"ユーザーは通知を見てコミュニケーションタブ側で対応する。"
    )
