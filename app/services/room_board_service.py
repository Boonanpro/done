# -*- coding: utf-8 -*-
"""部屋ボード v3 (room board) — 「合意済み目標カード」で部屋の現在地を見せる。

部屋には全体目標のカードだけが並ぶ。カード表面は4点のみ:
①何を目指すか(title) ②今どこで止まっているか(now) ③誰のボールか(ball)
④次に何が起きるか(next)。因果・経緯・サブタスク・イベント履歴は開いた時だけ。

チャット・音声・電話などどのサーフェスの発言も chat_messages に落ちるので、
そこを監視して新着ターンを定額CLI (run_oneshot_cli) で「消化」し、会話を
イベントとして目標の状態に反映する。更新は同一プロセス内の pub/sub で
SSE 購読者へ即時プッシュされる（フロントは /projects/{id}/board/stream を購読）。

設計原則 (ユーザーと合意済み):
- メインは「今」。達成・中止した目標はボードから消える (changes に記録)
- ダンは妥当な目標を自分で抽出してよい（合意の儀式なし）。ユーザーの指摘には即従う
- 優先順位は絞らない。全体感を提示するだけで、何をやるかはユーザーが決める
- 判断基準は room_board_rules.md（外部ファイル、使いながら編集）

有効化: python scripts/enable_room_board.py --title <部屋名>
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.environ.get("DAN_ROOM_BOARD_POLL_INTERVAL", "20"))
DIGEST_MODEL = os.environ.get("DAN_ROOM_BOARD_MODEL", "sonnet")
DIGEST_TIMEOUT = int(os.environ.get("DAN_ROOM_BOARD_TIMEOUT", "240"))

# 消化1回に食わせる上限（コスト・プロンプト肥大の抑制）
_MAX_MESSAGES_PER_DIGEST = 40
_MAX_CHARS_PER_MESSAGE = 1200
_MAX_TOTAL_CHARS = 24000

_CAP_GOALS = 8
_CAP_EVENTS_PER_GOAL = 12
_CAP_SUBTASKS = 10
_CAP_BLOCKERS = 5
_CAP_RECENT_CHANGES = 12

_ALLOWED_BALL = {"you", "dan", "external"}

# 同一部屋の消化の同時実行ガード（ポーラーと手動refreshの競合防止）
_digesting: set = set()
_digesting_lock = threading.Lock()


def _sb():
    from app.services.supabase_client import get_supabase_client
    return get_supabase_client().client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_board() -> Dict[str, Any]:
    return {
        "schema": 3,
        "goals": [],
        "recent_changes": [],
        "last_message_at": None,
        "updated_at": None,
        "version": 0,
    }


# ---------------------------------------------------------------- pub/sub (SSE)

_event_loop: Optional[asyncio.AbstractEventLoop] = None
_subscribers: Dict[str, Set["asyncio.Queue"]] = {}


async def subscribe_board(project_id: str) -> "asyncio.Queue":
    """SSEハンドラから呼ぶ。ボード更新が Queue に流れてくる。"""
    global _event_loop
    _event_loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue(maxsize=20)
    _subscribers.setdefault(project_id, set()).add(q)
    return q


def unsubscribe_board(project_id: str, q: "asyncio.Queue") -> None:
    try:
        _subscribers.get(project_id, set()).discard(q)
    except Exception:
        pass


def _publish_board(project_id: str, board: Dict[str, Any]) -> None:
    """ボード書き込み直後に購読者へプッシュ。ワーカースレッドからも呼べる。"""
    loop = _event_loop
    subs = _subscribers.get(project_id)
    if not loop or not subs:
        return

    def _fanout() -> None:
        for q in list(_subscribers.get(project_id, ())):
            try:
                q.put_nowait(board)
            except asyncio.QueueFull:
                pass

    try:
        loop.call_soon_threadsafe(_fanout)
    except Exception:
        pass


# ---------------------------------------------------------------- 読み書き

def get_project_with_board(
    project_id: Optional[str] = None, room_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """projects 行 (id, room_id, title, metadata) を返す。board は metadata.board。"""
    q = _sb().table("projects").select("id, room_id, title, metadata")
    if project_id:
        q = q.eq("id", project_id)
    elif room_id:
        q = q.eq("room_id", room_id)
    else:
        return None
    res = q.limit(1).execute()
    return res.data[0] if res.data else None


def get_board(project_id: Optional[str] = None, room_id: Optional[str] = None) -> Dict[str, Any]:
    row = get_project_with_board(project_id=project_id, room_id=room_id)
    meta = (row or {}).get("metadata") or {}
    board = meta.get("board")
    # 旧スキーマ (v1 tasks / v2 notes) のボードは空扱い → 次の消化で作り直される
    if board and "goals" not in board:
        board = None
    return {
        "enabled": bool(meta.get("board_enabled")),
        "board": board,
    }


def _read_meta(project_id: str) -> Dict[str, Any]:
    res = _sb().table("projects").select("metadata").eq("id", project_id).limit(1).execute()
    return (res.data[0].get("metadata") if res.data else None) or {}


def _write_board(project_id: str, board: Dict[str, Any]) -> None:
    """read-merge-write。metadata の他キー (model 等) を保持して board を差し替え、
    購読者へ即時プッシュする。"""
    meta = _read_meta(project_id)
    meta["board"] = board
    _sb().table("projects").update({"metadata": meta}).eq("id", project_id).execute()
    _publish_board(project_id, board)


def set_board_enabled(project_id: str, enabled: bool) -> None:
    meta = _read_meta(project_id)
    meta["board_enabled"] = enabled
    _sb().table("projects").update({"metadata": meta}).eq("id", project_id).execute()


def list_board_projects() -> List[Dict[str, Any]]:
    """board_enabled=true のプロジェクト一覧。JSONB の ->> でフィルタ。"""
    res = (
        _sb()
        .table("projects")
        .select("id, room_id, title, metadata")
        .filter("metadata->>board_enabled", "eq", "true")
        .execute()
    )
    return [r for r in (res.data or []) if r.get("room_id")]


# ---------------------------------------------------------------- 消化

_DIGEST_PROMPT = """あなたはチャット部屋の「部屋ボード」を管理する編集者です。
部屋ボードは、その部屋の全体目標ごとに「現在地」だけを常に最新で見せるカードUIです。

以下の【現在のボード】と【新しい会話】を読み、目標の状態を更新して JSON オブジェクトだけを返してください。

スキーマ:
{{
  "goals": [
    {{"id": "g1",
      "title": "なぜやりたいか＋何を目指すかを一文で",
      "waiting_on": "今の待ちを『◯◯待ち』の形で短く（例: 金先生の集計連絡待ち / LINE審査の結果待ち）。やったことは書かない",
      "waiting_note": "waiting_onの補足を短く（任意。小さく表示される。例: 9月中旬までに報酬額を伝える約束のため）",
      "ball": "you|dan|external",
      "ball_label": "待っている相手を短く（例: 金先生 / LINE / あなた）",
      "then": "その待ちが解消されたら次に何ができるか（一文・短く）",
      "due": "期日・見込み(任意)",
      "done_criteria": "何をもって完了か(任意)",
      "detail": "背景の説明(数行・任意。表面には出ない)",
      "new_events": ["今回の会話で実際に起きた出来事だけ(任意・内部用)"],
      "stale": false}}
  ],
  "changes": ["今回の更新で変わった点を短く。変化がなければ空配列"]
}}

【運用ルール】
{rules}

形式の決まり:
- id は既存を必ず維持。新規の目標は g+連番の新しい id。
- 目標は{cap_goals}枚以内。すべて日本語。
- 変化がなければ goals は現状のまま返し、changes と new_events は空。
- 出力は JSON オブジェクトのみ。コードフェンスや説明文は一切付けない。

【部屋タイトル】{title}

【現在のボード】
{board_json}

【新しい会話】（古い順。「ユーザー」=人間、「ダン」=AIアシスタント）
{conversation}
"""

_RULES_PATH = Path(__file__).resolve().parent / "room_board_rules.md"
_FALLBACK_RULES = (
    "- ユーザーがボードへの指示（カード消して等）を出したら最優先で従う\n"
    "- 目標は成果の単位。作業はサブタスク。達成・中止はカードごと削除して changes に記録\n"
    "- ball: you=ユーザーの番 / dan=ダン / external=外部・日時待ち\n"
    "- 推測で書かない。挨拶・雑談・動作テストからは何も作らない"
)


def _load_rules() -> str:
    try:
        text = _RULES_PATH.read_text(encoding="utf-8").strip()
        return text if text else _FALLBACK_RULES
    except Exception:
        return _FALLBACK_RULES


def _fetch_new_messages(room_id: str, since: Optional[str]) -> List[Dict[str, Any]]:
    q = (
        _sb()
        .table("chat_messages")
        .select("id, sender_type, content, created_at")
        .eq("room_id", room_id)
        .order("created_at", desc=True)
        .limit(_MAX_MESSAGES_PER_DIGEST)
    )
    if since:
        q = q.gt("created_at", since)
    res = q.execute()
    return list(reversed(res.data or []))  # 古い順に戻す


def _format_conversation(messages: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    total = 0
    for m in messages:
        who = "ダン" if (m.get("sender_type") == "ai") else "ユーザー"
        content = (m.get("content") or "").strip()
        if len(content) > _MAX_CHARS_PER_MESSAGE:
            content = content[:_MAX_CHARS_PER_MESSAGE] + "…(省略)"
        line = f"[{who}] {content}"
        total += len(line)
        if total > _MAX_TOTAL_CHARS:
            parts.append("…(これ以前は省略)")
            break
        parts.append(line)
    return "\n\n".join(parts)


def _parse_board_json(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s.lower().startswith("json"):
            s = s[4:].strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(s[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _goal_for_prompt(g: Dict[str, Any]) -> Dict[str, Any]:
    """LLMに渡す現在ボード: イベント履歴は直近2件だけに畳んでトークンを節約。"""
    out = {k: g.get(k) for k in (
        "id", "title", "waiting_on", "waiting_note", "ball", "ball_label", "then", "due",
        "done_criteria", "detail", "stale",
    ) if g.get(k) not in (None, "", [])}
    events = g.get("events") or []
    if events:
        out["recent_events"] = [e.get("text") for e in events[-2:]]
    return out


def _core_fields(g: Dict[str, Any]) -> tuple:
    return (g.get("title"), g.get("waiting_on"), g.get("waiting_note"), g.get("ball"), g.get("ball_label"), g.get("then"), g.get("due"))


def _normalize(new: Dict[str, Any], old: Dict[str, Any]) -> Dict[str, Any]:
    """LLM出力を検証してボード形式に整える。壊れた出力は旧値でフォールバック。"""
    board = dict(old)
    now = _now_iso()
    old_goals = {g["id"]: g for g in (old.get("goals") or [])}

    goals: List[Dict[str, Any]] = []
    seen_ids: set = set()
    for g in new.get("goals") or []:
        if not isinstance(g, dict):
            continue
        title = str(g.get("title") or "").strip()
        if not title:
            continue
        gid = str(g.get("id") or f"g{len(goals) + 1}")
        if gid in seen_ids:
            gid = f"g{len(goals) + 1}x"
        seen_ids.add(gid)
        prev = old_goals.get(gid)
        ball = str(g.get("ball") or "dan").strip().lower()
        goal: Dict[str, Any] = {
            "id": gid,
            "title": title[:100],
            "waiting_on": str(g.get("waiting_on") or "").strip()[:60],
            "waiting_note": str(g.get("waiting_note") or "").strip()[:120],
            "ball": ball if ball in _ALLOWED_BALL else "dan",
            "ball_label": str(g.get("ball_label") or "").strip()[:30],
            "then": str(g.get("then") or "").strip()[:140],
            "due": str(g.get("due") or "").strip()[:40],
            "done_criteria": str(g.get("done_criteria") or "").strip()[:160],
            "detail": str(g.get("detail") or "").strip()[:600],
            "stale": bool(g.get("stale")),
            "created_at": (prev or {}).get("created_at") or now,
        }
        # イラストURLは消化で消さず引き継ぐ（別途生成して付与される）
        if (prev or {}).get("image_url"):
            goal["image_url"] = prev["image_url"]
        # イベント履歴は蓄積（LLMは new_events だけ返す）
        events = list((prev or {}).get("events") or [])
        for ev in g.get("new_events") or []:
            text = str(ev).strip()[:160]
            if text and text not in {e.get("text") for e in events[-3:]}:
                events.append({"at": now, "text": text})
        goal["events"] = events[-_CAP_EVENTS_PER_GOAL:]
        # 中身が変わった時だけ updated_at を進める（stale判定・「動いた感」の元）
        if prev and _core_fields(prev) == _core_fields(goal):
            goal["updated_at"] = prev.get("updated_at") or now
        else:
            goal["updated_at"] = now
        goals.append(goal)

    if isinstance(new.get("goals"), list):
        board["goals"] = goals[:_CAP_GOALS]

    changes = [str(x).strip()[:200] for x in (new.get("changes") or []) if str(x).strip()]
    if changes:
        recent = list(old.get("recent_changes") or [])
        recent.extend({"at": now, "text": c} for c in changes[:5])
        board["recent_changes"] = recent[-_CAP_RECENT_CHANGES:]

    board["schema"] = 3
    board["version"] = int(old.get("version") or 0) + 1
    board["updated_at"] = now
    return board


def _digest_messages(
    title: str, board: Dict[str, Any], messages: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """会話1バッチをボードに消化して新しいボードを返す。失敗時 None。"""
    prompt = _DIGEST_PROMPT.format(
        cap_goals=_CAP_GOALS,
        rules=_load_rules(),
        title=title,
        board_json=json.dumps(
            {"goals": [_goal_for_prompt(g) for g in board.get("goals") or []]},
            ensure_ascii=False, indent=1,
        ),
        conversation=_format_conversation(messages),
    )
    from app.agent.cli_runner import run_oneshot_cli
    raw = run_oneshot_cli(prompt, model=DIGEST_MODEL, timeout=DIGEST_TIMEOUT)
    parsed = _parse_board_json(raw)
    if parsed is None:
        logger.warning("room board digest: unparsable LLM output: %r", (raw or "")[:200])
        return None
    return _normalize(parsed, board)


def digest_project(project: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
    """1プロジェクト分の消化。新着なし/ターン未完了ならスキップ。

    戻り値: {"digested": bool, "reason": str, "board": dict|None}
    """
    project_id = project["id"]
    room_id = project["room_id"]
    meta = project.get("metadata") or {}
    board = meta.get("board") or _empty_board()
    if "goals" not in board:  # 旧スキーマは作り直し
        board = _empty_board()

    with _digesting_lock:
        if room_id in _digesting:
            return {"digested": False, "reason": "already_running", "board": board}
        _digesting.add(room_id)
    try:
        since = None if force else board.get("last_message_at")
        messages = _fetch_new_messages(room_id, since)
        if not messages:
            return {"digested": False, "reason": "no_new_messages", "board": board}
        # ターン完了（=最後がダンの発言）を待ってから消化する。ユーザー発言だけの
        # 時点で消化すると、直後のダンの返答でもう一度消化することになり無駄。
        if not force and messages[-1].get("sender_type") != "ai":
            return {"digested": False, "reason": "turn_in_progress", "board": board}

        updated = _digest_messages(project.get("title") or "", board, messages)
        if updated is None:
            return {"digested": False, "reason": "parse_failed", "board": board}
        updated["last_message_at"] = messages[-1].get("created_at")
        _write_board(project_id, updated)
        logger.info(
            "room board digested (room=%s, v%s, %s msgs)", room_id, updated["version"], len(messages)
        )
        return {"digested": True, "reason": "ok", "board": updated}
    finally:
        with _digesting_lock:
            _digesting.discard(room_id)


def seed_from_history(
    project: Dict[str, Any],
    source_room_id: str,
    max_messages: int = 240,
    chunk_size: int = 40,
) -> Dict[str, Any]:
    """既存部屋の履歴を古い順にチャンク消化してボードを種付けする。

    直近40件だけの種付けだと部屋の全体感が落ちる（「こんだけだったっけ？」）ので、
    履歴を深く掃く。既存ボードは作り直し。カーソル(last_message_at)は進めない
    （ボード部屋自身の会話は初回消化で全件読まれる）。
    """
    project_id = project["id"]
    res = (
        _sb()
        .table("chat_messages")
        .select("id, sender_type, content, created_at")
        .eq("room_id", source_room_id)
        .order("created_at", desc=True)
        .limit(max_messages)
        .execute()
    )
    messages = list(reversed(res.data or []))
    if not messages:
        return {"digested": False, "reason": "no_source_messages", "board": None}

    board = _empty_board()
    chunks = [messages[i : i + chunk_size] for i in range(0, len(messages), chunk_size)]
    for idx, chunk in enumerate(chunks):
        updated = _digest_messages(project.get("title") or "", board, chunk)
        if updated is not None:
            board = updated
        logger.info("room board seed chunk %s/%s done (goals=%s)", idx + 1, len(chunks), len(board.get("goals") or []))
    # 種付け直後の「新規」印ラッシュを避ける: 種付け分は既存扱いにする
    seed_time = _now_iso()
    for g in board.get("goals") or []:
        g["created_at"] = g.get("created_at") or seed_time
    # カーソルを最新メッセージまで進める。空(None)にすると常駐ポーラーが
    # 直後に再消化して種付け結果を上書きしてしまう（古いコード稼働時は
    # 新フィールドが消える事故になる）。
    board["last_message_at"] = messages[-1].get("created_at")
    _write_board(project_id, board)
    return {"digested": True, "reason": "ok", "board": board, "chunks": len(chunks)}


# ---------------------------------------------------------------- ポーラー

_started = False


async def _poller_loop() -> None:
    await asyncio.sleep(15)  # サンドボックス起動直後の負荷を避ける
    while True:
        try:
            projects = await asyncio.to_thread(list_board_projects)
            for p in projects:
                try:
                    await asyncio.to_thread(digest_project, p)
                except Exception as e:
                    logger.warning("room board digest failed (room=%s): %s", p.get("room_id"), e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("room board poller cycle failed: %s", e)
        await asyncio.sleep(POLL_INTERVAL)


def start_board_poller() -> Optional["asyncio.Task"]:
    global _started, _event_loop
    if _started:
        return None
    if os.environ.get("DAN_ROOM_BOARD_POLLER_ENABLED", "1") != "1":
        logger.info("room board poller disabled by env")
        return None
    _started = True
    _event_loop = asyncio.get_event_loop()
    task = asyncio.get_event_loop().create_task(_poller_loop())
    logger.info("room board poller started (interval=%ss, model=%s)", POLL_INTERVAL, DIGEST_MODEL)
    return task
