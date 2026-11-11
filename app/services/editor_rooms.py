"""制作の部屋: エディターの中でダンと話す部屋（2026-11-11 本人「エディターの中にチャットが欲しい」）。

本体の部屋（素材と作品を持つ部屋 = asset room）ごとに、エディターの中だけで使う部屋を2種類持つ。
- ライブラリの部屋（content_id なし）: 制作ライブラリの「ダンと制作」の欄。素材集め・新しい作品の相談。
- 作品の部屋（content_id あり）: その作品のタイムラインを開いた画面の欄。そのタイムラインを直す話。

どちらも一覧に出さない部屋（projects.metadata.hidden）で、origin_room_id が本体の部屋。
metadata.editor = {asset_room_id, content_id, kind: library|content}。話すダンは同じ一人のダンで、
本体の部屋の履歴・記憶を読め（前置きの <place> に本体の部屋の id を書く）、本体の部屋のダンからも
制作の部屋の進みが読める（本体の部屋の前置きに制作の部屋の一覧と最後の発言を書く）。
素材とタイムラインは本体の部屋のもの（uploads/production-assets/<asset room>）を使う。
"""
from __future__ import annotations

import time
from typing import Any, Optional

_CACHE_SECONDS = 30.0
_info_cache: dict[str, tuple[float, Optional[dict[str, Any]]]] = {}
_children_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _sb():
    from app.services.supabase_client import get_supabase_client
    return get_supabase_client().client


def _editor_meta(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    meta = row.get("metadata") or {}
    ed = meta.get("editor") if isinstance(meta, dict) else None
    if not isinstance(ed, dict) or not ed.get("asset_room_id"):
        return None
    return ed


def _content_title(asset_room_id: str, content_id: str) -> str:
    try:
        from app.services import timeline_draft as td
        content = td._find_content(td._read_contents_raw(asset_room_id), content_id)
        return str((content or {}).get("title") or "")
    except Exception:
        return ""


async def ensure_room(user_id: str, asset_room_id: str, content_id: Optional[str] = None, sb=None) -> dict[str, Any]:
    """本体の部屋（と作品）の制作の部屋を返す。無ければ作る。{project_id, room_id, title, kind}。"""
    import asyncio
    from app.services.project_service import ProjectService

    sb = sb or _sb()
    content_id = (content_id or "").strip() or None
    kind = "content" if content_id else "library"

    def _find():
        rows = (sb.table("projects").select("id,room_id,title,metadata")
                .eq("origin_room_id", asset_room_id).eq("user_id", user_id).execute()).data or []
        for r in rows:
            ed = _editor_meta(r)
            if ed and (ed.get("content_id") or None) == content_id and r.get("room_id"):
                return {"project_id": r["id"], "room_id": r["room_id"], "title": r.get("title") or "", "kind": kind}, None
        parent = (sb.table("projects").select("id,title,metadata").eq("room_id", asset_room_id).limit(1).execute()).data or []
        return None, (parent[0] if parent else {})

    found, parent = await asyncio.to_thread(_find)
    if found:
        return found
    parent_title = str(parent.get("title") or "")
    if content_id:
        ctitle = await asyncio.to_thread(_content_title, asset_room_id, content_id) or content_id[:8]
        title = f"制作: {ctitle}"
        desc = (f"エディターで作品「{ctitle}」(content_id={content_id}) を開いた画面の右の「ダンと制作」の会話。"
                f"本体の部屋は「{parent_title}」(room_id={asset_room_id})。このタイムラインを一緒に作る・直す。")
    else:
        title = f"制作ライブラリ: {parent_title}"
        desc = (f"エディターの制作ライブラリの右の「ダンと制作」の会話。本体の部屋は「{parent_title}」(room_id={asset_room_id})。"
                "素材を集めて並べ、新しい作品を作り始める。")
    pmeta = parent.get("metadata") or {}
    metadata: dict[str, Any] = {"hidden": True, "editor": {
        "asset_room_id": asset_room_id, "content_id": content_id, "kind": kind}}
    if isinstance(pmeta, dict) and pmeta.get("model"):
        metadata["model"] = pmeta["model"]
    project = await ProjectService().create_project(
        user_id=user_id, title=title[:80], description=desc, origin_room_id=asset_room_id, metadata=metadata)
    _children_cache.pop(asset_room_id, None)
    return {"project_id": project.get("id"), "room_id": project.get("room_id"),
            "title": project.get("title") or title, "kind": kind}


def room_info(room_id: str, sb=None) -> Optional[dict[str, Any]]:
    """制作の部屋なら {asset_room_id, content_id, kind, title, parent_title}、そうでなければ None。"""
    if not room_id:
        return None
    hit = _info_cache.get(room_id)
    if hit and time.time() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    info: Optional[dict[str, Any]] = None
    try:
        sb = sb or _sb()
        rows = (sb.table("projects").select("title,metadata").eq("room_id", room_id).limit(1).execute()).data or []
        ed = _editor_meta(rows[0]) if rows else None
        if ed:
            parent = (sb.table("projects").select("id,title").eq("room_id", ed["asset_room_id"]).limit(1).execute()).data or []
            info = {"asset_room_id": str(ed["asset_room_id"]), "content_id": ed.get("content_id") or None,
                    "kind": ed.get("kind") or ("content" if ed.get("content_id") else "library"),
                    "title": rows[0].get("title") or "",
                    "parent_title": (parent[0].get("title") if parent else "") or "",
                    "parent_project_id": (parent[0].get("id") if parent else "") or ""}
    except Exception:
        info = None
    _info_cache[room_id] = (time.time(), info)
    return info


def asset_room(room_id: str) -> str:
    """素材とタイムラインを持つ部屋。制作の部屋なら本体の部屋、それ以外はその部屋自身。"""
    info = room_info(room_id)
    return info["asset_room_id"] if info else room_id


def children(asset_room_id: str, sb=None) -> list[dict[str, Any]]:
    """本体の部屋の制作の部屋の一覧（最後の発言の時刻と冒頭つき、新しい順）。"""
    hit = _children_cache.get(asset_room_id)
    if hit and time.time() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    out: list[dict[str, Any]] = []
    try:
        sb = sb or _sb()
        rows = (sb.table("projects").select("room_id,title,metadata")
                .eq("origin_room_id", asset_room_id).execute()).data or []
        rows = [r for r in rows if _editor_meta(r) and r.get("room_id")]
        if rows:
            rooms = (sb.table("chat_rooms").select("id,last_message_at,last_message_preview")
                     .in_("id", [r["room_id"] for r in rows]).execute()).data or []
            by_id = {r["id"]: r for r in rooms}
            for r in rows:
                ed = _editor_meta(r) or {}
                room = by_id.get(r["room_id"]) or {}
                out.append({"room_id": r["room_id"], "title": r.get("title") or "", "content_id": ed.get("content_id"),
                            "last_message_at": room.get("last_message_at") or "",
                            "preview": (room.get("last_message_preview") or "").replace("\n", " ")[:80]})
            out.sort(key=lambda x: x["last_message_at"] or "", reverse=True)
    except Exception:
        out = []
    _children_cache[asset_room_id] = (time.time(), out)
    return out


def context_lines(room_id: str) -> list[str]:
    """前置き <place> に足す行。制作の部屋なら本体の部屋とつながり、本体の部屋なら制作の部屋の一覧。"""
    info = room_info(room_id)
    lines: list[str] = []
    if info:
        a = info["asset_room_id"]
        lines.append(f"この部屋は制作の部屋（{'作品のタイムラインの画面' if info['content_id'] else '制作ライブラリ'}の右の「ダンと制作」）。"
                     f"本体の部屋は「{info['parent_title']}」(room_id={a})。素材と作品は本体の部屋の物"
                     f"（uploads/production-assets/{a}）を使う。")
        if info["content_id"]:
            lines.append(f"この部屋の作品: content_id={info['content_id']}。タイムラインは mcp__timeline__* で直す。")
        lines.append(f"本体の部屋の話（決まったこと・台本・素材の場所）は lookup(source=messages, room_id={a}) で読む。"
                     "記憶・ルールは本体の部屋と同じ。ほかの制作の部屋は下の一覧。")
        sibs = [c for c in children(a) if c["room_id"] != room_id]
        for c in sibs[:6]:
            lines.append(f"- {c['title']} (room_id={c['room_id']}) 最後: {c['last_message_at'][:16]} {c['preview']}")
        return lines
    kids = children(room_id)
    if kids:
        lines.append("この部屋のエディターの中の「ダンと制作」の会話（制作の部屋）。動画の作業の進みはここで話されている。"
                     "読む時は lookup(source=messages, room_id=…)。")
        for c in kids[:8]:
            lines.append(f"- {c['title']} (room_id={c['room_id']}) 最後: {c['last_message_at'][:16]} {c['preview']}")
    return lines
