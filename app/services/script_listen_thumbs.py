"""The thumbnails at the top of a talk script, edited in parts on the /script-listen screen (2026-11-20 本人「ダンと一緒に
サムネ編集して仕上げたりしたい…動画エディターにあるような機能がこの台本エディターの中にもほしい」).

Each picture in the doc's top part (◎サムネ …) can be tied to a thumbnail work (app/services/thumbnail_doc.py, the same
one the video editor opens) in the room the doc belongs to. The screen opens that work in the same thumbnail editor; when
the work has changed since the doc's picture was last made from it, the picture in the doc is replaced by a fresh export
(Docs API replaceImage, so other people who open the Google doc see the new thumbnail too).

Kept in ~/.dan/script-listen/thumbs/<doc>.json: {room, items: [{order, object, content_id, synced_rev}]}. ``order`` is the
picture's place among the top pictures (the object id can change when Docs replaces a picture).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from app.services import script_listen as S

DIR = Path.home() / '.dan' / 'script-listen' / 'thumbs'
_lock = threading.Lock()
_syncing: set[str] = set()
_failed: dict[str, float] = {}     # doc → when the last background sync failed (not tried again for a while)


def _path(doc_id: str) -> Path:
    return DIR / f'{doc_id}.json'


def load(doc_id: str) -> dict[str, Any]:
    try:
        return json.loads(_path(doc_id).read_text(encoding='utf-8'))
    except Exception:
        return {'room': None, 'items': []}


def _save(doc_id: str, data: dict[str, Any]) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(doc_id).with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(_path(doc_id))


def room_of(doc_id: str) -> str:
    """The room the doc belongs to (where its comments go), which also keeps its thumbnail works."""
    data = load(doc_id)
    if data.get('room'):
        return data['room']
    from app.services import gdoc_events as E
    room = E.room_for_file(doc_id)
    if not room:
        raise S.ListenError('この台本がどの部屋の物か分からないので、サムネを開けませんでした。', 409)
    return room


def top_images(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The pictures of the top part, in the doc's order: [{object, src, para}]."""
    out = []
    for u in S.outline(doc):
        if u['kind'] == 'image' and u.get('section') == 'top' and not u.get('ins') and not u.get('del'):
            out.append({'object': u.get('id'), 'src': u['src'], 'para': u.get('para')})
    return out


def _item(data: dict[str, Any], object_id: str | None, order: int | None) -> dict[str, Any] | None:
    items = data.get('items') or []
    hit = next((i for i in items if object_id and i.get('object') == object_id), None)
    if hit is None and order is not None:
        hit = next((i for i in items if i.get('order') == order), None)
    return hit


def annotate(doc_id: str, units: list[dict[str, Any]]) -> None:
    """Mark the top pictures with their place (``thumb_order``) and their work (``thumb``) for the screen."""
    data = load(doc_id)
    k = 0
    for u in units:
        if u['kind'] != 'image' or u.get('section') != 'top' or u.get('ins') or u.get('del'):
            continue
        u['thumb_order'] = k
        it = _item(data, u.get('id'), k)
        if it:
            u['thumb'] = it['content_id']
        k += 1


def _rev(room: str, content_id: str) -> int:
    from app.services import thumbnail_doc as td
    try:
        return int(td.get(room, content_id).get('rev') or 0)
    except Exception:
        return -1


def open_work(doc_id: str, object_id: str | None, order: int | None) -> dict[str, Any]:
    """{room_id, content_id} of the picture's thumbnail work. A picture not made of parts yet becomes a work holding the
    picture as one part, so it can be edited at once (text on it stays part of the picture)."""
    from app.services import thumbnail_doc as td
    from app.api import production_asset_routes as par
    with _lock:
        data = load(doc_id)
        room = data.get('room') or room_of(doc_id)
        it = _item(data, object_id, order)
        rev = _rev(room, it['content_id']) if it else -1
        for _ in range(3):                      # 作品が一瞬読めなくても、つないだ作品を1枚絵の新しい作品で置き換えない
            if not it or rev >= 0:
                break
            time.sleep(0.2)
            rev = _rev(room, it['content_id'])
        if it and rev >= 0:
            if object_id and it.get('object') != object_id:
                it['object'] = object_id
                _save(doc_id, {**data, 'room': room})
            return {'room_id': room, 'content_id': it['content_id']}
    doc = S.fetch(doc_id)
    imgs = top_images(doc)
    k = order if order is not None and 0 <= order < len(imgs) else next(
        (i for i, x in enumerate(imgs) if x['object'] == object_id), None)
    if k is None:
        raise S.ListenError('そのサムネはもうドキュメントにありません。', 409)
    r = httpx.get(imgs[k]['src'], timeout=30, follow_redirects=True)
    r.raise_for_status()
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(r.content)).convert('RGB')
    dest = par._room_dir(room) / 'thumbnails' / 'parts'
    dest.mkdir(parents=True, exist_ok=True)
    f = dest / f'doc-{doc_id[:10]}-{k}-{int(time.time())}.png'
    im.save(f)
    a = td.add_image_asset(room, f, f'サムネ{k + 1}（ドキュメントの絵）.png')
    w, h = 1920, round(1920 * im.height / im.width)
    tdoc = {'width': 1920, 'height': h if abs(h - 1080) > 4 else 1080, 'background': '#111',
            'parts': [{'id': 'photo', 'type': 'image', 'name': 'サムネの絵（文字も絵の一部）', 'src': td.media_url(room, a['id']),
                       'asset_id': a['id'], 'x': 0, 'y': 0, 'w': 1920, 'h': h}],
            'title': doc.get('title', '')}
    c = td.create(room, f"{doc.get('title', '台本')} サムネ{k + 1}", tdoc, [a['id']])
    with _lock:
        data = load(doc_id)
        items = [i for i in data.get('items') or [] if i.get('order') != k]
        items.append({'order': k, 'object': imgs[k]['object'], 'content_id': c['id'], 'synced_rev': 1})
        _save(doc_id, {'room': room, 'items': sorted(items, key=lambda i: i['order'])})
    return {'room_id': room, 'content_id': c['id']}


def snapshot(doc_id: str, content_id: str, marks: list | None = None, box: list | None = None) -> dict[str, Any]:
    """The work as it is now, as a PNG under /api/v1/files/ the chat can carry (2026-11-21 本人「要素クリックしても
    それがチャットに添付されない」). ``marks`` are the owner's pen lines; ``box`` (x, y, w, h in the work's pixels) is the
    picked part, drawn as a red frame. Only a work tied to this doc."""
    from app.services import thumbnail_doc as td
    from app.api import production_asset_routes as par
    data = load(doc_id)
    if not any(i.get('content_id') == content_id for i in data.get('items') or []):
        raise S.ListenError('このサムネはこの台本の物ではありません。', 404)
    room = data.get('room') or room_of(doc_id)
    lines = [m for m in (marks or []) if isinstance(m, dict) and isinstance(m.get('points'), list)][:200]
    if box and len(box) == 4:
        x, y, w, h = (float(v) for v in box)
        pad = 10
        x, y, w, h = x - pad, y - pad, w + 2 * pad, h + 2 * pad
        lines.append({'color': '#ff2a2a', 'width': 8, 'points': [[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]]})
    files = getattr(par, 'UPLOADS_DIR', None)
    if files is None:
        raise S.ListenError('絵の置き場所が見つかりませんでした。', 500)
    name = f"thumb-{content_id[:8]}-{int(time.time() * 1000)}.png"
    td.render(room, content_id, Path(files) / name, marks=lines, out_w=1280)
    return {'url': f'/api/v1/files/{name}'}


def tie(doc_id: str, order: int, content_id: str, room: str | None = None, synced: bool = False) -> dict[str, Any]:
    """Tie the doc's top picture number ``order`` (0 = first) to an existing thumbnail work (Dan, scripts)."""
    with _lock:
        data = load(doc_id)
        room = room or data.get('room') or room_of(doc_id)
        doc = S.fetch(doc_id)
        imgs = top_images(doc)
        if not 0 <= order < len(imgs):
            raise S.ListenError(f'上の部分の絵は {len(imgs)} 枚です。', 409)
        items = [i for i in data.get('items') or [] if i.get('order') != order]
        items.append({'order': order, 'object': imgs[order]['object'], 'content_id': content_id,
                      'synced_rev': _rev(room, content_id) if synced else 0})
        _save(doc_id, {'room': room, 'items': sorted(items, key=lambda i: i['order'])})
        return load(doc_id)


def status(doc_id: str) -> list[dict[str, Any]]:
    data = load(doc_id)
    room = data.get('room')
    out = []
    for it in data.get('items') or []:
        rev = _rev(room, it['content_id']) if room else -1
        out.append({**it, 'rev': rev, 'stale': rev > 0 and rev != it.get('synced_rev')})
    return out


def sync(doc_id: str, content_id: str | None = None) -> dict[str, Any]:
    """Put the current form of the doc's thumbnail works into the doc's pictures (only the ones that changed)."""
    from app.services import thumbnail_doc as td
    key = f'{doc_id}:{content_id or "*"}'
    with _lock:
        if key in _syncing:
            return {'busy': True}
        _syncing.add(key)
    try:
        data = load(doc_id)
        room = data.get('room')
        todo = [i for i in data.get('items') or [] if (content_id is None or i['content_id'] == content_id)
                and (r := _rev(room, i['content_id'])) > 0 and r != i.get('synced_rev')]
        if not todo:
            return {'changed': 0}
        origin = os.environ.get('DAN_PUBLIC_ORIGIN') or 'https://dan.paina.info'
        from app.paths import LIVE_ROOT
        files = LIVE_ROOT / 'uploads'          # the public file link Google reads the picture from (like add_image)
        files.mkdir(parents=True, exist_ok=True)
        made = []
        for it in todo:
            ex = td.export(room, it['content_id'])
            name = f"script-thumb-{it['content_id'][:8]}-rev{ex.get('rev') or 0}-{int(time.time())}.png"
            (files / name).write_bytes(Path(ex['path']).read_bytes())
            made.append((it, {**ex, 'url': f'/api/v1/files/{name}'}))
        S._follow(doc_id)
        with S._owner_lock:
            doc = S.fetch(doc_id)
            imgs = top_images(doc)
            reqs = []
            for it, ex in made:
                obj = it.get('object')
                if not any(x['object'] == obj for x in imgs):
                    if 0 <= it['order'] < len(imgs):
                        obj = imgs[it['order']]['object']
                    else:
                        continue
                reqs.append({'replaceImage': {'imageObjectId': obj, 'uri': f"{origin}{ex['url']}",
                                              'imageReplaceMethod': 'CENTER_CROP'}})
            if reqs:
                try:
                    S._docs('POST', f'{doc_id}:batchUpdate', doc['_account'],
                            body={'requests': reqs, 'writeControl': {'requiredRevisionId': doc['revisionId']}})
                except httpx.HTTPStatusError as exc:
                    raise S.ListenError(f'ドキュメントの絵を差し替えられませんでした（{exc.response.text[:200]}）', 502)
        after = top_images(S.fetch(doc_id))
        with _lock:
            data = load(doc_id)
            for it in data.get('items') or []:
                for done, ex in made:
                    if it['content_id'] == done['content_id']:
                        it['synced_rev'] = ex['rev']
                        if 0 <= it['order'] < len(after):
                            it['object'] = after[it['order']]['object']
            _save(doc_id, data)
        S._log_owner_action(doc_id, doc.get('title', ''), action='thumbnail', works=[i['content_id'] for i, _ in made])
        return {'changed': len(reqs)}
    finally:
        with _lock:
            _syncing.discard(key)


def sync_soon(doc_id: str) -> None:
    """Sync in the background when a work changed (Dan's thumb.py edits included); the screen asks every little while.
    After a failure the doc waits 5 minutes before the next try."""
    if time.time() - _failed.get(doc_id, 0) < 300:
        return
    if any(i['stale'] for i in status(doc_id)):
        def run():
            try:
                sync(doc_id)
            except Exception:
                _failed[doc_id] = time.time()
        threading.Thread(target=run, daemon=True).start()


def main() -> None:
    import sys
    a = sys.argv[1:]
    usage = ('python -m app.services.script_listen_thumbs status <doc> | sync <doc> | '
             'tie <doc> <何枚目(0から)> <content_id> [--synced]')
    if len(a) < 2:
        sys.exit(usage)
    doc = S.doc_id_from(a[1])
    if a[0] == 'status':
        print(json.dumps({'room': load(doc).get('room'), 'items': status(doc)}, ensure_ascii=False, indent=1))
    elif a[0] == 'sync':
        print(sync(doc))
    elif a[0] == 'tie' and len(a) >= 4:
        print(json.dumps(tie(doc, int(a[2]), a[3], synced='--synced' in a), ensure_ascii=False, indent=1))
    else:
        sys.exit(usage)


if __name__ == '__main__':
    main()
