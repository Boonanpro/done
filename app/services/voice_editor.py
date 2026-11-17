"""A call from the editor: where the owner was in the editor while he said each thing (2026-11-17, the owner's 「うん」).

Why: the owner wants to watch the video in the editor and say 「ここのテロップ、もう少し大きく」 while pointing at it, and
have Dan fix it in front of him. The work that fixes it is the same chat Dan the editor's chat reaches (voice_router
start_chat_dan → a job of the work's room with the timeline tools). That work starts seconds after the words, and by then
the playhead has moved on (or the owner kept playing), so what the editor shows *when the work starts* is not what he meant
by 「ここ」. So, while the owner speaks, the call records what the editor showed (playhead, selected clips, the spot on the
preview the mouse is on or was pressed) next to his words, and the work gets each of his turns with its moment and a frame
of the finished picture at that time with the spot marked.

Only the call of a work's room (editor_rooms: a room with a content) does this; the editor writes editor_state.json in the
asset room (production_asset_routes.post_editor_state). Nothing here is said into the call.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

READ_EVERY_S = .3      # the owner's words arrive as many small deltas: the editor's file is read at most this often
POINTER_FRESH_S = 6.0  # a spot the mouse left this long ago is no longer what he points at
MOMENTS_PER_TURN = 4
FRAMES = 2             # frames drawn for the work (the latest moments of the request)

def note_text(frames: str) -> str:
    """What the work is told about a call from the editor (the owner can rewrite it on /prompts: call/editor-call-note)."""
    from app.services import prompt_store
    return chr(10) * 2 + prompt_store.fill('call/editor-call-note', frames=frames)


def call_editor(room_id: str) -> dict[str, str] | None:
    """{asset_room_id, content_id} when the call's room is the room of one work in the editor, else None."""
    try:
        from app.services import editor_rooms
        info = editor_rooms.room_info(room_id)
    except Exception:  # noqa: BLE001
        return None
    if not info or not info.get('content_id') or not info.get('asset_room_id'):
        return None
    return {'asset_room_id': str(info['asset_room_id']), 'content_id': str(info['content_id'])}


def _state_path(asset_room_id: str) -> Path:
    from app.services import timeline_draft as td
    return td._room_dir(asset_room_id) / 'editor_state.json'


def moment_of(state: dict[str, Any] | None, content_id: str, now: float | None = None) -> dict[str, Any] | None:
    """The part of the editor's state that tells where the owner is, or None when it is not this work's editor."""
    if not isinstance(state, dict) or str(state.get('content_id') or '') != content_id or state.get('editor') != 'editor':
        return None
    now = time.time() if now is None else now
    out: dict[str, Any] = {'playhead': state.get('playhead'), 'playing': bool(state.get('playing')),
                           'selected': [str(s.get('id')) for s in (state.get('selected') or []) if isinstance(s, dict) and s.get('id')][:8]}
    p = state.get('pointer')
    if isinstance(p, dict) and (p.get('inside') or now - float(p.get('at') or 0) < POINTER_FRESH_S):
        out['pointer'] = {'x': round(float(p.get('x') or 0), 3), 'y': round(float(p.get('y') or 0), 3),
                          'ids': [str(i) for i in (p.get('ids') or [])][:6], 'pressed': bool(p.get('pressed'))}
    return out


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    def key(m):
        p = m.get('pointer') or {}
        ph = m.get('playhead')
        return (None if ph is None else round(float(ph) * 2) / 2, tuple(m.get('selected') or ()),
                (round(p.get('x', 0), 2), round(p.get('y', 0), 2), tuple(p.get('ids') or ())) if p else None)
    return key(a) == key(b)


class Moments:
    """Kept on the call's Dialogue (voice_sideband): `heard(turn)` on each delta of the owner's words."""

    def __init__(self, asset_room_id: str, content_id: str):
        self.asset_room_id, self.content_id = asset_room_id, content_id
        self.path = _state_path(asset_room_id)
        self.read_at = 0.0
        self.mtime = 0
        self.state: dict[str, Any] | None = None
        self._place = ''

    def place(self) -> str:
        """Where the call is, for whoever decides where a request goes (voice_router, voice_prefetch): without it
        「この字幕、『見るのがやめられず』に直して」 went to the general backend, which asked to share the screen (11/17)."""
        if not self._place:
            title = ''
            try:
                from app.services import timeline_live as tl
                content, _ = tl.live_sequence(self.asset_room_id, self.content_id)
                title = str((content or {}).get('title') or '')
            except Exception:  # noqa: BLE001
                pass
            from app.services import prompt_store
            self._place = prompt_store.fill('call/editor-place', title=title)
        return self._place

    def now_moment(self) -> dict[str, Any] | None:
        import json
        mono = time.monotonic()
        if mono - self.read_at >= READ_EVERY_S:
            self.read_at = mono
            try:
                st = self.path.stat()
                if st.st_mtime_ns != self.mtime:
                    self.mtime = st.st_mtime_ns
                    self.state = json.loads(self.path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                self.state = None
        return moment_of(self.state, self.content_id)

    def heard(self, turn: dict[str, Any]) -> None:
        m = self.now_moment()
        if m is None:
            return
        moments = turn.setdefault('editor', [])
        if moments and _same(moments[-1], m):
            return
        m['at'] = round(time.time(), 2)
        moments.append(m)
        del moments[:-MOMENTS_PER_TURN]


# -- what the work gets ------------------------------------------------------------------------------------------------

def _fmt(t: Any) -> str:
    try:
        t = max(0.0, float(t))
    except (TypeError, ValueError):
        return '?'
    m = int(t // 60)
    return f'{m}:{t - m * 60:04.1f}'


def _clips(asset_room_id: str, content_id: str) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """clip id -> clip (with its lane), asset id -> asset, of the work as it is now."""
    from app.services import timeline_live as tl
    _, seq = tl.live_sequence(asset_room_id, content_id)
    clips: dict[str, dict[str, Any]] = {}
    for lane, tr in enumerate((seq or {}).get('tracks') or []):
        for c in tr.get('clips') or []:
            clips[str(c.get('id'))] = {**c, '_lane': lane, '_track': tr.get('kind') or tr.get('type') or ''}
    for c in (seq or {}).get('scenes') or []:
        if isinstance(c, dict):
            clips.setdefault(str(c.get('id')), {**c, '_lane': '場面'})
    return clips, tl._assets(asset_room_id)


def clip_words(clip: dict[str, Any] | None, assets: dict[str, dict[str, Any]], cid: str) -> str:
    if not clip:
        return cid
    text = str(clip.get('text') or '').strip().replace('\n', ' ')
    asset = assets.get(str(clip.get('asset_id') or '')) or {}
    name = text and f'テロップ「{text[:30]}」' or str(asset.get('filename') or asset.get('name') or clip.get('kind') or 'クリップ')[:40]
    span = f"{_fmt(clip.get('timeline_start'))}〜{_fmt(clip.get('timeline_end'))}"
    return f"{name}（{cid}・段{clip.get('_lane')}・{span}）"


def _where(p: dict[str, Any]) -> str:
    x, y = float(p.get('x', 0)), float(p.get('y', 0))
    col = '左' if x < .34 else '右' if x > .66 else '真ん中'
    row = '上' if y < .34 else '下' if y > .66 else ''
    return f"画面の{row}{col}（左から{x * 100:.0f}%・上から{y * 100:.0f}%）"


def moment_text(m: dict[str, Any], clips: dict[str, dict[str, Any]], assets: dict[str, dict[str, Any]]) -> str:
    parts = [f"再生位置 {_fmt(m.get('playhead'))}{'（再生中）' if m.get('playing') else ''}"]
    if m.get('selected'):
        parts.append('選んでいた: ' + '、'.join(clip_words(clips.get(i), assets, i) for i in m['selected'][:4]))
    p = m.get('pointer')
    if p:
        what = '、'.join(clip_words(clips.get(i), assets, i) for i in (p.get('ids') or [])[:3]) or '何も無い所'
        parts.append(f"{'押した' if p.get('pressed') else '指していた'}所: {_where(p)}。そこにある物（上から）: {what}")
    return '〔エディター: ' + '。'.join(parts) + '〕'


def turns_text(turns: list[dict[str, Any]], asset_room_id: str, content_id: str, limit: int = 30000) -> str:
    """The call's transcript with each of the owner's turns followed by where he was in the editor while saying it."""
    try:
        clips, assets = _clips(asset_room_id, content_id)
    except Exception:  # noqa: BLE001
        clips, assets = {}, {}
    rows = []
    for t in turns:
        words = str(t.get('text') or '').strip()
        if not words:
            continue
        row = ('本人' if t.get('role') == 'user' else 'ダン') + ': ' + words
        if t.get('role') == 'user':
            row += ''.join(chr(10) + '  ' + moment_text(m, clips, assets) for m in (t.get('editor') or []))
        rows.append(row)
    return chr(10).join(rows)[-limit:]


def last_moment_text(turns: list[dict[str, Any]], asset_room_id: str, content_id: str) -> str:
    """Where the owner was in the editor at the end of his last turn ('' when nothing was recorded)."""
    m = latest_moments(turns, 1)
    if not m:
        return ''
    try:
        clips, assets = _clips(asset_room_id, content_id)
    except Exception:  # noqa: BLE001
        clips, assets = {}, {}
    return moment_text(m[-1], clips, assets)


def latest_moments(turns: list[dict[str, Any]], n: int = FRAMES) -> list[dict[str, Any]]:
    """The last moments of the owner's last turns that differ in where they were (newest last)."""
    out: list[dict[str, Any]] = []
    for t in reversed(turns):
        if t.get('role') != 'user':
            if out:
                break
            continue
        for m in reversed(t.get('editor') or []):
            if not any(_same(m, o) for o in out):
                out.insert(0, m)
            if len(out) >= n:
                return out
    return out


def frame_file(asset_room_id: str) -> Path:
    from app.services import timeline_draft as td
    return td._room_dir(asset_room_id) / 'call_frames' / f'call_{int(time.time())}_{uuid.uuid4().hex[:6]}.png'


def draw_frame(asset_room_id: str, content_id: str, m: dict[str, Any], dest: Path) -> str | None:
    """The finished picture at the moment's playhead, the pointed spot marked in red. None when it cannot be drawn."""
    from app.services import editor_instructions as ei
    from app.services import sequence_window
    from app.services import timeline_live as tl
    _, seq = tl.live_sequence(asset_room_id, content_id)
    if not isinstance(seq, dict) or m.get('playhead') is None:
        return None
    try:
        res = sequence_window.render_frames(asset_room_id, seq, [float(m['playhead'])], dest.parent)
        if not res.get('ok'):
            return None
        raw = Path(res['paths'][0])
        p = m.get('pointer')
        if p:
            ok = ei._draw_marks(raw, dest, {'kind': 'marker', 'data': {'point': {'x': p['x'], 'y': p['y']}}})
            raw.unlink(missing_ok=True)
            return str(dest) if ok else None
        raw.replace(dest)
        return str(dest)
    except Exception:  # noqa: BLE001 — the work goes on without the picture
        return None


def note_for(asset_room_id: str, content_id: str, turns: list[dict[str, Any]]) -> tuple[str, list[tuple[dict[str, Any], Path]]]:
    """The paragraph the call's work gets, and the frames to draw (moment, where) after the work has started."""
    todo = [(m, frame_file(asset_room_id)) for m in latest_moments(turns)]
    frames = ''
    if todo:
        frames = ('その時の完成画面の絵（指していた所は赤い丸。裏で描いているので、まだ無ければ少し待つ。描けなかった時は render_frame で'
                  'その再生位置を見る）: ' + '、'.join(f"{_fmt(m.get('playhead'))} → {p}" for m, p in todo) + '（Read で開ける）。')
    return note_text(frames), todo
