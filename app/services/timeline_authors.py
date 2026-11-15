"""Who changed each clip of a work's timeline, when, and what.

2026-11-15 本人「俺が動かした。誰が動かしたかどうか分からないなら分かるようにしないと」: the room's Dan
found a clip moved and had to ask the owner whether they had moved it. Every write of a timeline now
records, per clip, the last change and who made it:
  * the owner's hand in the editor (PATCH /contents/{id} from the editor screen)
  * Dan: the room's conversation, a parallel job of the room (with its title), an editor job, a voice edit

Layout: {room_dir}/clip_authors/{content_id}.json = {"clips": {clip_id: last}, "log": [recent entries]}.
Display/diagnostic only: a failure here never fails the save that triggered it.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "uploads" / "production-assets"
_LOG_KEEP = 300
OWNER = {"kind": "owner", "label": "みきさん"}

# What changed, in the owner's words. Keys not listed fall under その他の設定.
_KEY_WORDS = [
    ({"timeline_start", "timeline_end"}, None),  # handled specially (位置 / 長さ)
    ({"source_start", "source_end"}, "使う範囲"),
    ({"track"}, "段"),
    ({"volume", "muted", "fade_in", "fade_out", "audio_keys"}, "音量"),
    ({"position", "transform_keys", "crop", "fit", "scale", "rotation"}, "画面での大きさ・位置"),
    ({"text", "words"}, "文字"),
    ({"style"}, "字の見た目"),
    ({"asset_id"}, "素材"),
    ({"speed"}, "速さ"),
    ({"opacity", "blend", "grade", "scene"}, "見た目"),
    ({"region", "region_keys", "effect_color", "blur_track"}, "ぼかし・枠"),
    ({"label"}, "名前"),
    ({"video_enabled", "hidden"}, "表示"),
]


def _room_dir(room_id: str) -> Path:
    return UPLOAD_ROOT / room_id


def _path(room_id: str, content_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(content_id))
    return _room_dir(room_id) / "clip_authors" / f"{safe}.json"


@contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
    except ImportError:  # Windows: no lock (the old single-writer behaviour)
        yield
        return
    fd = os.open(str(path.with_suffix(".lock")), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _index(seq: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for n, t in enumerate((seq or {}).get("tracks") or []):
        tid = t.get("id") or f"#{n}"
        for c in t.get("clips") or []:
            if c.get("id") is None:
                continue
            row = {k: v for k, v in c.items() if k not in ("track", "layer")}
            row["track"] = tid  # the lane's identity, not its index (adding a lane below must not "move" every clip)
            row["_lane"] = n
            out[str(c["id"])] = row
    return out


def _close(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(float(a) - float(b)) < 1e-4
    return a == b


def _what(before: dict[str, Any], after: dict[str, Any], keys: set[str]) -> list[str]:
    words: list[str] = []
    if keys & {"timeline_start", "timeline_end"}:
        d0 = _f(after.get("timeline_start")) - _f(before.get("timeline_start"))
        d1 = _f(after.get("timeline_end")) - _f(before.get("timeline_end"))
        words.append("位置" if abs(d0 - d1) < 1e-3 else "長さ")
    for group, word in _KEY_WORDS[1:]:
        if keys & group and word not in words:
            words.append(word)
    known = set().union(*(g for g, _ in _KEY_WORDS))
    if keys - known and "その他の設定" not in words:
        words.append("その他の設定")
    return words


def diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Per-clip changes between two sequences, keyed by clip id; lane identity by track id."""
    old, new = _index(before), _index(after)
    rows = []
    for cid in sorted(old.keys() | new.keys()):
        a, b = old.get(cid), new.get(cid)
        if a is None:
            rows.append({"clip_id": cid, "added": True, "what": ["追加"], "lane": b["_lane"],
                         "start": b.get("timeline_start"), "end": b.get("timeline_end")})
            continue
        if b is None:
            rows.append({"clip_id": cid, "removed": True, "what": ["削除"], "lane": a["_lane"],
                         "start": a.get("timeline_start"), "end": a.get("timeline_end")})
            continue
        keys = {k for k in (a.keys() | b.keys()) - {"_lane"} if not _close(a.get(k), b.get(k))}
        if not keys:
            continue
        small = {k for k in keys if k in ("timeline_start", "timeline_end", "source_start", "source_end", "volume", "track")}
        rows.append({"clip_id": cid, "what": _what(a, b, keys), "lane": b["_lane"],
                     "start": b.get("timeline_start"), "end": b.get("timeline_end"),
                     "before": {k: a.get(k) for k in sorted(small)}, "after": {k: b.get(k) for k in sorted(small)}})
    return rows


def actor_for_job(job_id: str | None) -> dict[str, Any]:
    """Who a draft without an explicit actor belongs to, from its job id."""
    j = str(job_id or "")
    if j.startswith("live_"):
        return {"kind": "dan", "label": "ダン（通話・すぐの直し）", "job_id": j}
    if j.startswith("chat_"):
        return {"kind": "dan", "label": "ダン（会話）", "job_id": j}
    return {"kind": "dan", "label": "ダン（制作の作業）", "job_id": j}


def record(room_id: str, content_id: str, before: dict[str, Any] | None, after: dict[str, Any] | None,
           actor: dict[str, Any], tool: str | None = None) -> int:
    """Remember who made the changes between `before` and `after`. Returns how many clips changed."""
    try:
        changes = diff(before, after)
        if not changes:
            return 0
        now = time.time()
        who = {"kind": str(actor.get("kind") or "dan"), "label": str(actor.get("label") or "ダン")}
        for k in ("job_id", "job_title"):
            if actor.get(k):
                who[k] = actor[k]
        if tool:
            who["tool"] = tool
        p = _path(room_id, content_id)
        with _locked(p):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            clips = data.get("clips") if isinstance(data.get("clips"), dict) else {}
            log = data.get("log") if isinstance(data.get("log"), list) else []
            for ch in changes:
                clips[ch["clip_id"]] = {**who, "t": now, "what": ch["what"],
                                        **({"removed": True} if ch.get("removed") else {}),
                                        **({"added": True} if ch.get("added") else {}),
                                        **({"before": ch["before"], "after": ch["after"]} if ch.get("before") else {})}
            log.append({**who, "t": now, "changes": changes[:40], "count": len(changes)})
            data = {"clips": clips, "log": log[-_LOG_KEEP:]}
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, p)
        return len(changes)
    except Exception:  # noqa: BLE001 — never fail the save
        return 0


def read(room_id: str, content_id: str) -> dict[str, Any]:
    try:
        data = json.loads(_path(room_id, content_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"clips": {}, "log": []}
    return {"clips": data.get("clips") or {}, "log": data.get("log") or []}


def last_by(room_id: str, content_id: str, clip_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
    clips = read(room_id, content_id)["clips"]
    if clip_ids is None:
        return clips
    return {str(c): clips[str(c)] for c in clip_ids if str(c) in clips}


def _clock(t: float) -> str:
    from datetime import datetime, timedelta, timezone
    return datetime.fromtimestamp(t, timezone(timedelta(hours=9))).strftime("%m/%d %H:%M")


def short(entry: dict[str, Any] | None) -> str:
    """One line for the tools: 「みきさん 11/15 16:12 位置・使う範囲」."""
    if not entry:
        return ""
    return f"{entry.get('label')} {_clock(_f(entry.get('t')))} {'・'.join(entry.get('what') or [])}".strip()


def history_text(room_id: str, content_id: str, clip_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Recent changes for the timeline tool: newest first, optionally only one clip's."""
    data = read(room_id, content_id)
    rows = []
    for e in reversed(data["log"]):
        chs = e.get("changes") or []
        if clip_id:
            chs = [c for c in chs if c.get("clip_id") == clip_id]
            if not chs:
                continue
        rows.append({"who": e.get("label"), "kind": e.get("kind"), "when": _clock(_f(e.get("t"))),
                     "job_id": e.get("job_id"), "tool": e.get("tool"), "count": e.get("count", len(chs)),
                     "changes": [{k: c.get(k) for k in ("clip_id", "what", "lane", "start", "end", "before", "after")
                                  if c.get(k) is not None} for c in chs[:12]]})
        if len(rows) >= limit:
            break
    out: dict[str, Any] = {"ok": True, "history": rows}
    if clip_id:
        out["last"] = data["clips"].get(clip_id)
    if not rows:
        out["note"] = "記録はありません（記録を始める前の変更は分かりません）"
    return out


def owner_recent_text(room_id: str, content_id: str, hours: float = 6.0, limit: int = 8) -> str:
    """Lines for the room's prompt: clips the owner moved by hand recently, so Dan does not ask who did it."""
    data = read(room_id, content_id)
    since = time.time() - hours * 3600
    rows = []
    for e in reversed(data["log"]):
        if _f(e.get("t")) < since:
            break
        if e.get("kind") != "owner":
            continue
        for c in (e.get("changes") or [])[:6]:
            rows.append(f"{_clock(_f(e.get('t')))} {c.get('clip_id')}（段{c.get('lane')}）{'・'.join(c.get('what') or [])}")
        if len(rows) >= limit:
            break
    if not rows:
        return ""
    return ("## みきさんが画面で直した所（最近）\n"
            "次のクリップはみきさん自身が手で動かした。誰が動かしたか本人に聞かない。戻さず、その形を前提に直す。\n"
            + "\n".join(f"- {r}" for r in rows[:limit]))
