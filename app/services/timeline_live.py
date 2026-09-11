"""Live timeline access for chat / voice Dan (outside an agent job).

Two lanes for "talk → the editor changes":
  * fast lane  — apply_edit(): ONE validated command on a fresh draft, committed with
    compare-and-swap right away (seconds). The voice agent calls this directly for
    small structural edits (move / trim / frame / blur / caption / property).
  * heavy lane — delegate to Dan with timeline_refs (the agent session gets the full
    timeline MCP); see realtime_routes / chat_routes.

Both read editor_context(): what the user's native editor shows right now, so "here"
and "this clip" resolve to the playhead and selection instead of a guess.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

from app.services import timeline_commands as tc
from app.services import timeline_context as tcx
from app.services import timeline_draft as td

FAST_OPS = {
    "move_clip", "trim_clip", "remove_clip", "split_clip", "set_clip", "set_clip_props",
    "add_region", "set_region", "add_caption", "add_clip", "add_audio", "add_overlay", "insert_freeze",
}


def _assets(room_id: str) -> dict[str, dict[str, Any]]:
    p = td._room_dir(room_id) / "assets.json"
    if not p.exists():
        return {}
    return {str(a.get("id")): a for a in json.loads(p.read_text(encoding="utf-8")) if isinstance(a, dict)}


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def editor_state(room_id: str, max_age_s: float = 900.0) -> dict[str, Any] | None:
    p = td._room_dir(room_id) / "editor_state.json"
    try:
        st = p.stat()
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or time.time() - st.st_mtime > max_age_s:
        return None
    data["age_s"] = round(time.time() - st.st_mtime, 1)
    if str(data.get("editor") or "") != "editor":
        # library screen: no content is actually open (the id is just the first doc entry)
        data["content_id"] = ""
    return data


def live_sequence(room_id: str, content_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    contents = td._read_contents_raw(room_id)
    content = td._find_content(contents, content_id)
    if content is None:
        return None, None
    return content, td._content_sequence(content)


def editor_context(room_id: str, content_id: str | None = None, with_outline: bool = True) -> dict[str, Any]:
    """Editor presence + (optionally) the outline of the open content."""
    st = editor_state(room_id)
    cid = content_id or (str(st.get("content_id")) if st else "")
    out: dict[str, Any] = {"editor_open": bool(st), "content_id": cid or None}
    if st:
        out.update({"playhead": st.get("playhead"), "playing": st.get("playing"),
                    "selected": st.get("selected") or [], "screen": st.get("editor")})
    if not cid:
        out["note"] = "エディタは開いていない。content_id を指定するか、ユーザーにどの動画か聞く"
        return out
    content, seq = live_sequence(room_id, cid)
    if seq is None:
        out["note"] = f"content {cid} にタイムラインが無い"
        return out
    out["title"] = content.get("title")
    assets = _assets(room_id)
    if with_outline:
        out["outline"] = tcx.timeline_outline(seq, assets)
    if st and st.get("playhead") is not None:
        out["clips_under_playhead"] = tc.clips_at(seq, assets, t=_f(st.get("playhead")))
    return out


def apply_edit(room_id: str, content_id: str, op: str, args: dict[str, Any],
               scope: dict | None = None, expected_hash: str | None = None) -> dict[str, Any]:
    """One command → validate → CAS commit. Returns the command result plus commit info."""
    if op not in FAST_OPS:
        return {"ok": False, "error": f"op must be one of {sorted(FAST_OPS)}"}
    args = dict(args or {})
    try:
        draft = td.create_draft(room_id, content_id, job_id=f"live_{int(time.time())}")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    seq = draft["sequence"]
    if expected_hash and draft["base_hash"] != expected_hash:
        td.discard_draft(room_id, draft["draft_id"], lambda *_: None)
        return {"ok": False, "error": "指示後に動画が変わりました。現在の画面で指示し直してください", "conflict": True}
    if scope is not None:
        draft["edit_scope"] = scope
    assets = _assets(room_id)
    baseline = set(tc.validate_sequence(seq, assets, asset_dir=str(td._room_dir(room_id))))
    fn = getattr(tc, op)
    try:
        if op in {"remove_clip", "move_clip", "split_clip", "set_clip", "set_region", "add_region", "add_caption"}:
            result = fn(seq, **args)
        else:
            result = fn(seq, assets, **args)
    except TypeError as exc:
        return {"ok": False, "error": f"bad arguments for {op}: {exc}"}
    if not result.get("ok"):
        td.discard_draft(room_id, draft["draft_id"], lambda *_: None)
        return result
    changes = describe_changes(draft['base_sequence'], seq)
    if td.sequence_hash(seq) == draft['base_hash']:
        td.discard_draft(room_id, draft['draft_id'], lambda *_: None)
        return {'ok': False, 'changed': False, 'committed': False,
                'error': '変更前と同じ状態です。変更は保存されていません。指定を確認してください。'}
    draft["log"].append({"t": time.time(), "tool": op, "args": args})
    td.save_draft(draft)

    def _validate(sequence, rid):
        probs = tc.validate_sequence(sequence, _assets(rid), asset_dir=str(td._room_dir(rid)))
        return [p for p in probs if p not in baseline]

    commit = td.commit_draft(room_id, draft["draft_id"], _validate)
    if not commit.get("ok"):
        td.discard_draft(room_id, draft["draft_id"], lambda *_: None)
        return {"ok": False, "error": "; ".join(commit.get("problems") or ["commit failed"]),
                "conflict": commit.get("conflict", False)}
    # caption PNGs are NOT baked here (a browser spawn ≈ 40s would defeat the fast lane);
    # the editor preview draws captions live and the exporter bakes missing PNGs itself.
    before_ids = {str(c.get('id')) for t in draft['base_sequence'].get('tracks', []) for c in t.get('clips', [])}
    new_ids = [str(c.get('id')) for t in seq.get('tracks', []) for c in t.get('clips', []) if str(c.get('id')) not in before_ids]
    return {**result, "committed": True, "draft_id": draft["draft_id"], "new_clip_ids": new_ids,
            "changed": True, "changes": changes,
            "sequence_hash": td.sequence_hash(seq),
            "note": "エディタに反映します。再生して結果を確認できます"}


def describe_changes(before, after):
    def indexed(seq):
        return {c['id']: dict(c, lane=n) for n,t in enumerate(seq.get('tracks', [])) for c in t.get('clips', [])}
    old, new = indexed(before), indexed(after)
    result = []
    for cid in sorted(old.keys() | new.keys()):
        a, b = old.get(cid, {}), new.get(cid, {})
        if a == b:
            continue
        c = b or a
        keys = [k for k in a.keys() | b.keys() if a.get(k) != b.get(k)]
        result.append({'clip_id': cid, 'text': c.get('text'), 'start': c.get('timeline_start'),
                       'end': c.get('timeline_end'), 'removed': not bool(b),
                       'before': {k:a.get(k) for k in keys}, 'after': {k:b.get(k) for k in keys}})
    return result


def _bake_caption_png(room_id: str, seq: dict[str, Any], args: dict[str, Any]) -> None:
    """Caption PNG cache for export parity (same routine the MCP server uses)."""
    import os
    import sys

    os.environ.setdefault("DAN_ROOM_ID", room_id)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app import timeline_mcp_server as mcp  # noqa: WPS433

    mcp.ROOM_ID = room_id
    text = str(args.get("text") or "")
    style = args.get("style") if isinstance(args.get("style"), dict) else None
    if "clip_id" in args:
        for tr in seq.get("tracks") or []:
            for cl in tr.get("clips") or []:
                if str(cl.get("id")) == str(args.get("clip_id")):
                    text, style = str(cl.get("text") or ""), cl.get("style")
    if text:
        mcp._ensure_caption_png(text, style if isinstance(style, dict) else None)


def render_frame_b64(room_id: str, content_id: str, t: float, half: bool = True) -> dict[str, Any]:
    _, seq = live_sequence(room_id, content_id)
    if seq is None:
        return {"ok": False, "error": "content has no timeline"}
    room = td._room_dir(room_id)
    res = tcx.render_timeline_frames(seq, str(room), [float(t)], out_dir=str(room / "drafts"))
    if not res.get("ok"):
        return res
    path = Path(res["paths"][0])
    data = path.read_bytes()
    if half:
        try:
            from io import BytesIO

            from PIL import Image

            im = Image.open(path).convert("RGB")
            im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
            buf = BytesIO()
            im.save(buf, format="JPEG", quality=82)
            data = buf.getvalue()
            return {"ok": True, "t": t, "image": "data:image/jpeg;base64," + base64.b64encode(data).decode()}
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "t": t, "image": "data:image/png;base64," + base64.b64encode(data).decode()}


def context_text(room_id: str, content_id: str | None = None) -> str:
    """Short Japanese context block for prompts (delegation / chat turn)."""
    ctx = editor_context(room_id, content_id, with_outline=False)
    if not ctx.get("editor_open") and not ctx.get("content_id"):
        return ""
    lines = ["## 動画エディタの状態（ユーザーが今見ているもの）"]
    lines.append(f"- content_id: {ctx.get('content_id')}  title: {ctx.get('title') or ''}")
    if ctx.get("editor_open"):
        lines.append(f"- 再生位置: {ctx.get('playhead')}秒 ({'再生中' if ctx.get('playing') else '停止中'})")
        sel = ctx.get("selected") or []
        if sel:
            lines.append("- 選択中クリップ: " + "; ".join(
                f"{s.get('id')} lane{s.get('lane')} {_f(s.get('timeline_start')):.2f}-{_f(s.get('timeline_end')):.2f}"
                + (f" text=\"{s.get('text')}\"" if s.get('text') else "") for s in sel[:8]))
        under = ctx.get("clips_under_playhead") or []
        if under:
            lines.append("- 再生位置にあるクリップ: " + "; ".join(
                f"{c.get('clip_id')}({c.get('kind')} lane{c.get('lane')})" for c in under[:10]))
    else:
        lines.append("- エディタは閉じている（最後に開いていたコンテンツを対象にする）")
    lines.append("- 『ここ』『これ』『この字幕』は上の再生位置・選択を指す。mcp__timeline__* で編集し、触るのは指示された箇所だけ。")
    return "\n".join(lines)
