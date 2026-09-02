# -*- coding: utf-8 -*-
"""部屋ボード (room board) — 部屋ごとの「現在地」フリーボード。

会話ログとは別に、部屋の現在地を「付箋 (notes) + 因果矢印 (arrows)」として
projects.metadata.board (JSONB) に永続化する。チャット・音声・電話など、
どのサーフェスの発言も最終的に chat_messages に落ちるので、そこを監視して
新着ターンを定額CLI (run_oneshot_cli) で「消化」し、ボードを更新する。

設計原則 (ユーザーと合意済み):
- メインは「今」。完了・中止した付箋はボードから消える (changes に記録)
- 付箋の色 = 手番 (you=ユーザー / dan=ダン / wait=外部・日時待ち)
- 矢印 = 因果・依存。「これが決まる/終わると、これが動く」
- 優先順位は絞らない。全体感を提示するだけで、何をやるかはユーザーが決める
- 付箋の配置 (positions) はユーザーのドラッグを尊重し、消化で上書きしない

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
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.environ.get("DAN_ROOM_BOARD_POLL_INTERVAL", "20"))
DIGEST_MODEL = os.environ.get("DAN_ROOM_BOARD_MODEL", "sonnet")
DIGEST_TIMEOUT = int(os.environ.get("DAN_ROOM_BOARD_TIMEOUT", "240"))

# 消化1回に食わせる上限（コスト・プロンプト肥大の抑制）
_MAX_MESSAGES_PER_DIGEST = 40
_MAX_CHARS_PER_MESSAGE = 1200
_MAX_TOTAL_CHARS = 24000

_CAP_NOTES = 16
_CAP_ARROWS = 14
_CAP_RECENT_CHANGES = 12

_ALLOWED_OWNER = {"you", "dan", "wait"}
_ALLOWED_KIND = {"action", "decision"}

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
        "notes": [],
        "arrows": [],
        "positions": {},
        "recent_changes": [],
        "last_message_at": None,
        "updated_at": None,
        "version": 0,
    }


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
    # 旧スキーマ (v1: tasks/decisions) のボードは空扱い → 次の消化で作り直される
    if board and "notes" not in board:
        board = None
    return {
        "enabled": bool(meta.get("board_enabled")),
        "board": board,
    }


def _read_meta(project_id: str) -> Dict[str, Any]:
    res = _sb().table("projects").select("metadata").eq("id", project_id).limit(1).execute()
    return (res.data[0].get("metadata") if res.data else None) or {}


def _write_board(project_id: str, board: Dict[str, Any]) -> None:
    """read-merge-write。metadata の他キーを保持し、positions は直前の値と統合する
    （消化中にユーザーがドラッグした配置を消化の書き込みで潰さないため）。"""
    meta = _read_meta(project_id)
    current = meta.get("board") or {}
    merged_pos = dict(current.get("positions") or {})
    merged_pos.update(board.get("positions") or {})
    note_ids = {n["id"] for n in board.get("notes") or []}
    board["positions"] = {k: v for k, v in merged_pos.items() if k in note_ids}
    meta["board"] = board
    _sb().table("projects").update({"metadata": meta}).eq("id", project_id).execute()


def update_positions(project_id: str, positions: Dict[str, Any]) -> Dict[str, Any]:
    """ユーザーのドラッグ配置を保存する。{note_id: {x, y}} をマージ。"""
    meta = _read_meta(project_id)
    board = meta.get("board") or _empty_board()
    pos = dict(board.get("positions") or {})
    for note_id, p in positions.items():
        try:
            pos[str(note_id)] = {"x": round(float(p["x"]), 1), "y": round(float(p["y"]), 1)}
        except Exception:
            continue
    board["positions"] = pos
    meta["board"] = board
    _sb().table("projects").update({"metadata": meta}).eq("id", project_id).execute()
    return board


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
部屋ボードはホワイトボードに付箋を貼ったような現在地マップです。見た人が
「この部屋は今どういう状況か」を一目で掴むためのもので、優先順位は付けません。

以下の【現在のボード】と【新しい会話】を読み、ボードを更新して JSON オブジェクトだけを返してください。

スキーマ:
{{
  "notes": [
    {{"id": "n1", "title": "付箋の見出し(短く)", "body": "補足1行(任意)",
      "owner": "you|dan|wait", "kind": "action|decision",
      "live": "ダンがまさに今している作業の一言(owner=danで実行中のみ)",
      "due": "期日・見込み(任意, 例: 9/3ごろ)", "stale": false}}
  ],
  "arrows": [{{"from": "n1", "to": "n2", "label": "矢印の意味を短く(任意)"}}],
  "changes": ["今回の更新で変わった点を短く。変化がなければ空配列"]
}}

【運用ルール】
{rules}

形式の決まり:
- id は既存を必ず維持。新規は n+連番の新しい id。
- kind: action=やること / decision=確定した方針・前提
- 付箋は{cap_notes}枚以内。すべて日本語。
- 変化がなければ notes/arrows は現状のまま返し、changes は空配列。
- 出力は JSON オブジェクトのみ。コードフェンスや説明文は一切付けない。

【部屋タイトル】{title}

【現在のボード】
{board_json}

【新しい会話】（古い順。「ユーザー」=人間、「ダン」=AIアシスタント）
{conversation}
"""

_RULES_PATH = Path(__file__).resolve().parent / "room_board_rules.md"
_FALLBACK_RULES = (
    "- ユーザーがボードへの指示（付箋消して等）を出したら最優先で従う\n"
    "- 完了・中止は付箋ごと削除して changes に記録\n"
    "- owner: you=ユーザーの番 / dan=ダン / wait=外部・日時待ち\n"
    "- 矢印は因果・依存のみ。推測で書かない。挨拶・雑談からは何も作らない"
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


def _normalize(new: Dict[str, Any], old: Dict[str, Any]) -> Dict[str, Any]:
    """LLM出力を検証してボード形式に整える。壊れた出力は旧値でフォールバック。"""
    board = dict(old)

    notes: List[Dict[str, Any]] = []
    seen_ids: set = set()
    for n in new.get("notes") or []:
        if not isinstance(n, dict):
            continue
        title = str(n.get("title") or "").strip()
        if not title:
            continue
        nid = str(n.get("id") or f"n{len(notes) + 1}")
        if nid in seen_ids:
            nid = f"n{len(notes) + 1}x"
        seen_ids.add(nid)
        owner = str(n.get("owner") or "wait").strip().lower()
        kind = str(n.get("kind") or "action").strip().lower()
        note = {
            "id": nid,
            "title": title[:60],
            "body": str(n.get("body") or "").strip()[:160],
            "owner": owner if owner in _ALLOWED_OWNER else "wait",
            "kind": kind if kind in _ALLOWED_KIND else "action",
            "stale": bool(n.get("stale")),
        }
        live = str(n.get("live") or "").strip()
        if live and note["owner"] == "dan":
            note["live"] = live[:80]
        due = str(n.get("due") or "").strip()
        if due:
            note["due"] = due[:40]
        notes.append(note)
    if isinstance(new.get("notes"), list):
        board["notes"] = notes[:_CAP_NOTES]

    note_ids = {n["id"] for n in board.get("notes") or []}
    arrows: List[Dict[str, Any]] = []
    for a in new.get("arrows") or []:
        if not isinstance(a, dict):
            continue
        frm, to = str(a.get("from") or ""), str(a.get("to") or "")
        if frm not in note_ids or to not in note_ids or frm == to:
            continue
        arrow = {"from": frm, "to": to}
        label = str(a.get("label") or "").strip()
        if label:
            arrow["label"] = label[:20]
        arrows.append(arrow)
    if isinstance(new.get("arrows"), list):
        board["arrows"] = arrows[:_CAP_ARROWS]

    changes = [str(x).strip()[:200] for x in (new.get("changes") or []) if str(x).strip()]
    if changes:
        recent = list(old.get("recent_changes") or [])
        now = _now_iso()
        recent.extend({"at": now, "text": c} for c in changes[:5])
        board["recent_changes"] = recent[-_CAP_RECENT_CHANGES:]

    board["version"] = int(old.get("version") or 0) + 1
    board["updated_at"] = _now_iso()
    return board


def _digest_messages(
    title: str, board: Dict[str, Any], messages: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """会話1バッチをボードに消化して新しいボードを返す。失敗時 None。"""
    prompt = _DIGEST_PROMPT.format(
        cap_notes=_CAP_NOTES,
        rules=_load_rules(),
        title=title,
        board_json=json.dumps(
            {"notes": board.get("notes") or [], "arrows": board.get("arrows") or []},
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
    if "notes" not in board:  # 旧スキーマは作り直し
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
        logger.info("room board seed chunk %s/%s done (notes=%s)", idx + 1, len(chunks), len(board.get("notes") or []))
    board["last_message_at"] = None
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
    global _started
    if _started:
        return None
    if os.environ.get("DAN_ROOM_BOARD_POLLER_ENABLED", "1") != "1":
        logger.info("room board poller disabled by env")
        return None
    _started = True
    task = asyncio.get_event_loop().create_task(_poller_loop())
    logger.info("room board poller started (interval=%ss, model=%s)", POLL_INTERVAL, DIGEST_MODEL)
    return task
