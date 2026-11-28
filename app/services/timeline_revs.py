"""Versions of a work's timeline, so a save from the editor never erases what it has not seen.

The editor saves the whole sequence it holds. A screen that was left open (a tab asleep in the
background, another device) still holds the timeline as it was when it last synced; when it saved
on 2026-11-25 it wrote that old timeline back and erased 72 changes Dan had made in between
(sound effects, replaced pictures, added pictures) — the owner opened the work and saw none of
the edits.

Every timeline the server hands out carries `_rev`, a hash of its content. The server keeps a
compressed copy of each version under {room}/timeline_revs/{content_id}/{rev}.json.gz. When the
editor saves it says which version it started from (`base_rev`). If the live timeline is no longer
that version, the save is merged clip by clip:

- a clip the owner did not change on their screen keeps its live form (Dan's edit stays),
- a clip only the owner changed takes the owner's form,
- a clip both changed takes the owner's form (the hand on the screen wins),
- clips the owner added are added, clips Dan added stay, deletions follow whoever made them.
"""
from __future__ import annotations

import copy
import gzip
import json
import os
import time
from pathlib import Path
from typing import Any

from app.services.timeline_draft import _room_dir, sequence_hash

REV_KEY = "_rev"
_KEEP_SECONDS = 7 * 24 * 3600
_KEEP_MAX = 600


def rev_of(seq: dict[str, Any] | None) -> str:
    if not isinstance(seq, dict):
        return ""
    return sequence_hash({k: v for k, v in seq.items() if k != REV_KEY})


def _dir(room_id: str, content_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(content_id))
    return _room_dir(room_id) / "timeline_revs" / safe


def remember(room_id: str, content_id: str, seq: dict[str, Any] | None) -> str:
    """Stamp `_rev` on the sequence (in place) and keep a copy of this version. Returns the rev."""
    if not isinstance(seq, dict):
        return ""
    rev = rev_of(seq)
    seq[REV_KEY] = rev
    try:
        d = _dir(room_id, content_id)
        p = d / f"{rev}.json.gz"
        if p.exists():
            os.utime(p, None)
        else:
            d.mkdir(parents=True, exist_ok=True)
            body = {k: v for k, v in seq.items() if k != REV_KEY}
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(json.dumps(body, ensure_ascii=False).encode("utf-8"), 5))
            os.replace(tmp, p)
            _prune(d)
    except OSError:
        pass
    return rev


def _prune(d: Path) -> None:
    files = sorted(d.glob("*.json.gz"), key=lambda f: f.stat().st_mtime, reverse=True)
    now = time.time()
    for n, f in enumerate(files):
        if n >= _KEEP_MAX or now - f.stat().st_mtime > _KEEP_SECONDS:
            try:
                f.unlink()
            except OSError:
                pass


def load(room_id: str, content_id: str, rev: str) -> dict[str, Any] | None:
    if not rev or not all(c in "0123456789abcdef" for c in rev):
        return None
    p = _dir(room_id, content_id) / f"{rev}.json.gz"
    try:
        return json.loads(gzip.decompress(p.read_bytes()).decode("utf-8"))
    except (OSError, ValueError):
        return None


def stamp_contents(room_id: str, contents: list[dict[str, Any]]) -> None:
    """Make sure every timeline handed out says which version it is (a writer that does not
    stamp, e.g. an older script, is caught up here). Only the response is changed."""
    for c in contents:
        tl = c.get("timeline") if isinstance(c.get("timeline"), dict) else None
        seq = tl.get("sequence") if tl else None
        if isinstance(seq, dict) and seq.get(REV_KEY) != rev_of(seq):
            remember(room_id, str(c.get("id")), seq)


def _canon(v: Any) -> Any:
    # the browser writes 1.0 as 1 and drops null keys it never set: the same clip must compare equal
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, dict):
        return {k: _canon(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [_canon(x) for x in v]
    return v


def _sig(v: Any) -> str:
    return json.dumps(_canon(v), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _index(seq: dict[str, Any] | None) -> dict[str, tuple[int, int, dict[str, Any]]]:
    out: dict[str, tuple[int, int, dict[str, Any]]] = {}
    for lane, tr in enumerate((seq or {}).get("tracks") or []):
        if not isinstance(tr, dict):
            continue
        for order, clip in enumerate(tr.get("clips") or []):
            if isinstance(clip, dict) and clip.get("id") is not None:
                out[str(clip["id"])] = (lane, order, clip)
    return out


def _merge_clip(be: tuple[int, int, dict[str, Any]], me: tuple[int, int, dict[str, Any]],
                le: tuple[int, int, dict[str, Any]]) -> tuple[int, int, dict[str, Any]]:
    """A clip both sides changed: live's clip with the fields the owner changed taken from the
    owner (a field both changed → the owner's). The lane is the owner's if the owner moved it."""
    bc, mc, lc = be[2], me[2], le[2]
    out = copy.deepcopy(lc)
    for k in dict.fromkeys([*bc.keys(), *mc.keys()]):
        if _sig(mc.get(k)) == _sig(bc.get(k)):
            continue
        if k in mc and mc[k] is not None:
            out[k] = copy.deepcopy(mc[k])
        else:
            out.pop(k, None)
    lane = me[0] if me[0] != be[0] else le[0]
    return (lane, me[1] if lane == me[0] else le[1], out)


def merge(base: dict[str, Any], mine: dict[str, Any], live: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Three-way merge of the owner's save (`mine`, made from `base`) onto the live timeline.

    Returns the merged sequence and counts {kept_live, from_owner, conflicts_owner_won}."""
    b, m, l = _index(base), _index(mine), _index(live)
    stats = {"kept_live": 0, "from_owner": 0, "conflicts_owner_won": 0}
    placed: dict[int, list[tuple[float, int, int, dict[str, Any]]]] = {}

    def put(entry: tuple[int, int, dict[str, Any]] | None, src_rank: int) -> None:
        if entry is None:
            return
        lane, order, clip = entry
        placed.setdefault(lane, []).append((float(clip.get("timeline_start") or 0), src_rank, order, copy.deepcopy(clip)))

    for cid in list(dict.fromkeys([*l.keys(), *m.keys(), *b.keys()])):
        be, me, le = b.get(cid), m.get(cid), l.get(cid)
        key = lambda e: None if e is None else _sig([e[0], e[2]])  # noqa: E731
        kb, km, kl = key(be), key(me), key(le)
        if km == kb:
            put(le, 0)
            if kl != kb:
                stats["kept_live"] += 1
        elif kl == kb:
            put(me, 1)
            stats["from_owner"] += 1
        elif be is not None and me is not None and le is not None:
            # Both changed the clip. Merge field by field: the owner's screen wins only the fields
            # the owner changed. 2026-11-28: the owner closed a gap (every later clip's
            # timeline_start moved) while Dan zoomed those clips into the text being read — the
            # whole-clip rule wrote the owner's old transform back and erased every zoom.
            put(_merge_clip(be, me, le), 1)
            stats["conflicts_owner_won"] += 1
        else:
            put(me, 1)
            stats["conflicts_owner_won"] += 1

    # top-level fields and lane settings: the owner's value where the owner changed it, else live
    out: dict[str, Any] = {}
    for k in dict.fromkeys([*live.keys(), *mine.keys()]):
        if k in ("tracks", REV_KEY):
            continue
        if _sig(mine.get(k)) != _sig(base.get(k)):
            if k in mine:
                out[k] = copy.deepcopy(mine[k])
        elif k in live:
            out[k] = copy.deepcopy(live[k])
    bt, mt, lt = (s.get("tracks") or [] for s in (base, mine, live))
    lanes = max(len(mt), len(lt), (max(placed) + 1) if placed else 0)
    tracks = []
    for n in range(lanes):
        def props(ts: list) -> dict[str, Any] | None:
            return {k: v for k, v in ts[n].items() if k != "clips"} if n < len(ts) and isinstance(ts[n], dict) else None
        pb, pm, pl = props(bt), props(mt), props(lt)
        chosen = pm if (_sig(pm) != _sig(pb) and pm is not None) else (pl if pl is not None else pm)
        tr = copy.deepcopy(chosen or {})
        tr["clips"] = [c for *_, c in sorted(placed.get(n, []), key=lambda e: (e[0], e[1], e[2]))]
        tracks.append(tr)
    out["tracks"] = tracks
    return out, stats
