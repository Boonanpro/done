"""部品で持つサムネ（2026-11-18 本人「サムネの微調整の往復に時間がかかりすぎる。自分で手で直せる・書き込みで指示できる・
その場で変わる様子が見える仕組みがほしい」→ 提案「部品に分けたサムネ」「描き込んで直す」を「うん」）。

前のサムネは1枚の平らな画像で、文字も矢印も絵に焼き付けていたので、「文字を少し上へ」だけでもダンがプログラムを直して
作り直す往復が要った。今は作品（contents.json の1件、format='thumbnail'）の timeline.thumbnail に、背景・人物・文字・
矢印を別々の部品として持つ（形は frontend/src/components/thumbnail/thumb-doc.ts）。
- 本人はエディターで部品をつかんで動かす・大きさを変える・文字を打ち直す・色を変える（保存は PUT /thumbnail）。
- ダンは scripts/thumb.py で同じ JSON の数値を直す（save）。開いている画面は1.5秒ごとに読み直して、目の前で変わる。
- 絵の中身を変える頼みは repaint: 指した範囲だけを gpt-image で描き直し、範囲の外は1画素も変えない。
- 書き出し・ダンが見る絵は render: エディターと同じ描き方の /thumbnail-frame を headless Chromium で撮る。
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FORMAT = 'thumbnail'


def cli() -> str:
    """ダンがサムネを直す道具を呼ぶ形（この作りのコードの道具を、どこからでも同じ形で）。"""
    return f"{sys.executable} {ROOT / 'scripts' / 'thumb.py'}"


def _par():
    from app.api import production_asset_routes as par
    return par


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_thumbnail(content: dict[str, Any] | None) -> bool:
    if not isinstance(content, dict):
        return False
    tl = content.get('timeline') if isinstance(content.get('timeline'), dict) else {}
    return content.get('format') == FORMAT or isinstance(tl.get('thumbnail'), dict)


def _find(room_id: str, content_id: str) -> dict[str, Any]:
    c = next((c for c in _par()._read_contents(room_id) if str(c.get('id')) == str(content_id)), None)
    if not c:
        raise ValueError('作品が見つかりません')
    return c


def get(room_id: str, content_id: str) -> dict[str, Any]:
    c = _find(room_id, content_id)
    doc = ((c.get('timeline') or {}).get('thumbnail')) or {}
    return doc if isinstance(doc, dict) else {}


def _history_path(room_id: str, content_id: str) -> Path:
    d = _par()._room_dir(room_id) / 'thumbnails' / content_id
    d.mkdir(parents=True, exist_ok=True)
    return d / 'history.jsonl'


def save(room_id: str, content_id: str, doc: dict[str, Any], actor: str = 'owner') -> dict[str, Any]:
    """サムネの部品を保存する。rev を1つ進め、前の形を履歴に残す（ダンの直しを本人が元に戻せるように）。"""
    from app.services.timeline_draft import ContentsLock
    par = _par()
    if not isinstance(doc, dict) or not isinstance(doc.get('parts'), list):
        raise ValueError('サムネの形が正しくありません（parts が要ります）')
    with ContentsLock(room_id):
        contents = par._read_contents(room_id)
        c = next((c for c in contents if str(c.get('id')) == str(content_id)), None)
        if not c:
            raise ValueError('作品が見つかりません')
        tl = c.get('timeline') if isinstance(c.get('timeline'), dict) else {}
        before = tl.get('thumbnail') if isinstance(tl.get('thumbnail'), dict) else None
        rev = int((before or {}).get('rev') or 0) + 1
        doc = {**doc, 'rev': rev, 'saved_by': actor, 'saved_at': _now()}
        c['timeline'] = {**tl, 'thumbnail': doc}
        c['format'] = FORMAT
        c['updated_at'] = _now()
        par._write_contents(room_id, contents)
    if before is not None:
        hp = _history_path(room_id, content_id)
        with hp.open('a', encoding='utf-8') as f:
            f.write(json.dumps(before, ensure_ascii=False) + '\n')
        try:   # 古い分は捨てる（200回分）
            rows = hp.read_text(encoding='utf-8').splitlines()
            if len(rows) > 240:
                hp.write_text('\n'.join(rows[-200:]) + '\n', encoding='utf-8')
        except OSError:
            pass
    return doc


def undo(room_id: str, content_id: str, actor: str = 'dan') -> dict[str, Any]:
    """1つ前に保存した形へ戻す。"""
    hp = _history_path(room_id, content_id)
    rows = hp.read_text(encoding='utf-8').splitlines() if hp.exists() else []
    if not rows:
        raise ValueError('戻せる前の形がありません')
    prev = json.loads(rows[-1])
    hp.write_text(('\n'.join(rows[:-1]) + '\n') if rows[:-1] else '', encoding='utf-8')
    doc = save(room_id, content_id, prev, actor)
    rows2 = hp.read_text(encoding='utf-8').splitlines()   # save が今の形を足したので、その1行は捨てる
    hp.write_text(('\n'.join(rows2[:-1]) + '\n') if rows2[:-1] else '', encoding='utf-8')
    return doc


def create(room_id: str, title: str, doc: dict[str, Any], asset_ids: list[str] | None = None,
           video_id: str | None = None) -> dict[str, Any]:
    """新しいサムネの作品。動画の作品（video_id）とひと組で作る。直す時は今の作品を save で直し、これは使わない
    （2026-11-21 本人「今あるサムネを直しているだけなのに、なんでサムネが増えていくんだ」）。"""
    from app.services.timeline_draft import ContentsLock
    par = _par()
    now = _now()
    content = {
        'id': str(uuid.uuid4()), 'room_id': room_id, 'title': title, 'format': FORMAT, 'status': 'draft',
        'asset_ids': list(asset_ids or []), 'timeline': {'thumbnail': {**doc, 'rev': 1}}, 'outputs': [],
        'created_at': now, 'updated_at': now,
    }
    if video_id:
        content['video_id'] = video_id
    with ContentsLock(room_id):
        contents = par._read_contents(room_id)
        if video_id and not any(str(c.get('id')) == str(video_id) and not is_thumbnail(c) for c in contents):
            raise ValueError('つなぐ動画の作品が見つかりません')
        contents.append(content)
        par._write_contents(room_id, contents)
    return content


# ── 動画とひと組（2026-11-21 本人「サムネイルは必ず動画のエディター、動画とセットで基本的に作る」）──────────────

def thumbnails_of(room_id: str, video_id: str, contents: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """その動画のサムネ（控えに回した物は除く）。作った順＝1枚目が表のサムネ。"""
    rows = contents if contents is not None else _par()._read_contents(room_id)
    out = [c for c in rows if is_thumbnail(c) and str(c.get('video_id') or '') == str(video_id) and not c.get('archived')]
    return sorted(out, key=lambda c: (c.get('pattern_order') if isinstance(c.get('pattern_order'), int) else 99,
                                      str(c.get('created_at') or '')))


def _patch(room_id: str, content_id: str, fn) -> dict[str, Any]:
    from app.services.timeline_draft import ContentsLock
    par = _par()
    with ContentsLock(room_id):
        contents = par._read_contents(room_id)
        c = next((c for c in contents if str(c.get('id')) == str(content_id)), None)
        if not c:
            raise ValueError('作品が見つかりません')
        fn(c, contents)
        c['updated_at'] = _now()
        par._write_contents(room_id, contents)
        return c


def attach(room_id: str, thumb_id: str, video_id: str, order: int | None = None) -> dict[str, Any]:
    """サムネの作品を動画の作品につなぐ（一覧から外れ、動画のエディターの「サムネ」に出る）。"""
    def fn(c, contents):
        if not is_thumbnail(c):
            raise ValueError('サムネの作品ではありません')
        if not any(str(v.get('id')) == str(video_id) and not is_thumbnail(v) for v in contents):
            raise ValueError('つなぐ動画の作品が見つかりません')
        c['video_id'] = video_id
        c['archived'] = False
        if order is not None:
            c['pattern_order'] = int(order)
    return _patch(room_id, thumb_id, fn)


def archive(room_id: str, thumb_id: str, video_id: str | None = None) -> dict[str, Any]:
    """増えてしまったサムネを消さずに控えへ回す（どの一覧にも出ない。戻すのは attach）。"""
    def fn(c, contents):
        if not is_thumbnail(c):
            raise ValueError('サムネの作品ではありません')
        c['archived'] = True
        if video_id:
            c['video_id'] = video_id
    return _patch(room_id, thumb_id, fn)


# ── 案を増やす（2026-11-23 本人「サムネは何パターンか作りたいんで自由に増やせるように。canvaみたいな使い心地」）──
# 本人がエディターの下の「＋」で足す時だけ増やす。ダンが直す時は今の案を save で直し、勝手に増やさない。

def _normalize_order(rows: list[dict[str, Any]], video_id: str) -> list[dict[str, Any]]:
    """その動画の案に 0,1,2… の番号を振り直す（今の並び＝表のサムネが先頭のまま）。"""
    pats = thumbnails_of('', video_id, rows)
    for i, c in enumerate(pats):
        c['pattern_order'] = i
    return pats


def add_pattern(room_id: str, video_id: str, from_id: str | None = None) -> dict[str, Any]:
    """動画に案を1つ足す。from_id があればその案の写し、無ければ白紙。足した案は一番後ろ。"""
    import copy
    from app.services.timeline_draft import ContentsLock
    par = _par()
    now = _now()
    with ContentsLock(room_id):
        contents = par._read_contents(room_id)
        video = next((c for c in contents if str(c.get('id')) == str(video_id) and not is_thumbnail(c)), None)
        if not video:
            raise ValueError('動画の作品が見つかりません')
        pats = _normalize_order(contents, video_id)
        src = None
        if from_id:
            src = next((c for c in pats if str(c.get('id')) == str(from_id)), None)
            if not src:
                raise ValueError('写す案が見つかりません')
        base = ((src or {}).get('timeline') or {}).get('thumbnail') if src else None
        if isinstance(base, dict):
            doc = copy.deepcopy(base)
            for k in ('instructions', 'saved_by', 'saved_at'):
                doc.pop(k, None)
        else:
            first = ((pats[0].get('timeline') or {}).get('thumbnail') or {}) if pats else {}
            doc = {'width': int(first.get('width') or 1920), 'height': int(first.get('height') or 1080),
                   'background': '#111111', 'parts': [], 'title': first.get('title') or video.get('title') or ''}
        doc['rev'] = 1
        used = {str(c.get('title') or '') for c in pats}
        n = len(pats) + 1
        while f'案{n}' in used:
            n += 1
        content = {
            'id': str(uuid.uuid4()), 'room_id': room_id, 'title': f'案{n}', 'format': FORMAT, 'status': 'draft',
            'asset_ids': list((src or {}).get('asset_ids') or []), 'timeline': {'thumbnail': doc}, 'outputs': [],
            'created_at': now, 'updated_at': now, 'video_id': video_id, 'pattern_order': len(pats),
        }
        contents.append(content)
        par._write_contents(room_id, contents)
    return content


def set_pattern_order(room_id: str, video_id: str, ids: list[str]) -> list[dict[str, Any]]:
    """案の並びを決める（先頭が表のサムネ）。ids に無い案は後ろに今の順で残す。"""
    from app.services.timeline_draft import ContentsLock
    par = _par()
    with ContentsLock(room_id):
        contents = par._read_contents(room_id)
        pats = thumbnails_of('', video_id, contents)
        if not pats:
            raise ValueError('案がありません')
        pos = {str(i): k for k, i in enumerate(ids)}
        was = {str(c.get('id')): k for k, c in enumerate(pats)}
        pats.sort(key=lambda c: (pos.get(str(c.get('id')), len(ids)), was[str(c.get('id'))]))
        for k, c in enumerate(pats):
            c['pattern_order'] = k
            c['updated_at'] = _now()
        par._write_contents(room_id, contents)
    return pats


def remove_pattern(room_id: str, thumb_id: str) -> dict[str, Any]:
    """案を消す（消さずに控えへ回す。最後の1つは消さない）。"""
    c = _find(room_id, thumb_id)
    vid = str(c.get('video_id') or '')
    if vid and len(thumbnails_of(room_id, vid)) <= 1:
        raise ValueError('最後の1つの案は消せません')
    return archive(room_id, thumb_id)


def add_uploaded_image(room_id: str, content_id: str, data: bytes, filename: str) -> dict[str, Any]:
    """本人が貼り付けた・落とした画像を、そのサムネの部品の絵にする（素材に登録して URL を返す）。"""
    from PIL import Image
    import io
    _find(room_id, content_id)
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            fmt = (im.format or 'PNG').upper()
    except Exception as exc:
        raise ValueError('画像として読めませんでした') from exc
    ext = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'GIF': '.gif'}.get(fmt, '.png')
    d = _par()._room_dir(room_id) / 'thumbnails' / content_id / 'uploads'
    d.mkdir(parents=True, exist_ok=True)
    path = d / f'{uuid.uuid4().hex[:12]}{ext}'
    if ext == '.png' and fmt != 'PNG':
        with Image.open(io.BytesIO(data)) as im:
            im.save(path, 'PNG')
    else:
        path.write_bytes(data)
    row = add_image_asset(room_id, path, filename or path.name, generated_by='owner:thumbnail')
    meta = row.get('metadata') or {}
    return {'asset_id': row['id'], 'src': media_url(room_id, row['id']), 'width': meta.get('width'), 'height': meta.get('height')}


def video_for_doc(room_id: str, doc_id: str, title: str = '') -> str:
    """台本に合う動画の作品。台本がつないである動画→同じ台本のサムネがつながっている動画→無ければ空のタイムラインの
    動画の作品を新しく作って台本をつなぐ（撮影前の台本でも、サムネは動画とひと組にする）。"""
    from app.services.timeline_draft import ContentsLock
    par = _par()
    with ContentsLock(room_id):
        contents = par._read_contents(room_id)
        hit = next((c for c in contents if not is_thumbnail(c) and c.get('script_doc') == doc_id), None)
        if hit:
            return str(hit['id'])
        try:
            from app.services import script_listen_thumbs as T
            tied = {i.get('content_id') for i in (T.load(doc_id).get('items') or [])}
        except Exception:
            tied = set()
        vids = [c.get('video_id') for c in contents if c.get('id') in tied and c.get('video_id')]
        for v in vids:
            if any(str(x.get('id')) == str(v) and not is_thumbnail(x) for x in contents):
                return str(v)
        now = _now()
        video = {'id': str(uuid.uuid4()), 'room_id': room_id, 'title': title or '台本の動画', 'format': '16:9',
                 'status': 'draft', 'asset_ids': [], 'outputs': [], 'script_doc': doc_id,
                 'timeline': {'sequence': {'format': '16:9', 'frame_rate': 30, 'duration': 0, 'tracks': []}},
                 'created_at': now, 'updated_at': now}
        contents.append(video)
        par._write_contents(room_id, contents)
        return video['id']


# ── 絵の素材 ─────────────────────────────────────────────────────────────────────

def media_url(room_id: str, asset_id: str) -> str:
    return f"/api/v1/production-assets/media?room_id={room_id}&asset_id={asset_id}&variant=original"


def add_image_asset(room_id: str, path: Path, filename: str, generated_by: str = 'dan:thumbnail') -> dict[str, Any]:
    """部品の絵を作品の部屋の素材にする（エディターは media の URL で読む）。"""
    from PIL import Image
    par = _par()
    with Image.open(path) as im:
        w, h = im.size
    row = {
        'id': uuid.uuid4().hex[:12], 'room_id': room_id, 'kind': 'image', 'source_type': 'generated',
        'original_uri': str(path), 'local_path': str(path), 'filename': filename,
        'metadata': {'width': w, 'height': h, 'thumbnail_part': True}, 'status': 'ready',
        'created_at': _now(), 'updated_at': _now(), 'generated_by': generated_by,
    }
    rows = par._read_assets(room_id)
    rows.append(row)
    par._write_assets(room_id, rows)
    return row


def versioned(room_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    """絵の部品の住所に、その絵のファイルの版（大きさと更新時刻）を付けた写しを返す。

    同じ素材のファイルを描き直した時（画質を落とした・切り抜き直した）、住所が同じだと本人の画面が
    手元に控えた前の絵を出し続けていた（11/21 中村さんの部品の画質を落としたのにエディターで変わらない）。
    """
    parts = doc.get('parts') if isinstance(doc, dict) else None
    if not isinstance(parts, list):
        return doc
    out = []
    for p in parts:
        if isinstance(p, dict) and p.get('type') == 'image' and p.get('asset_id'):
            f = asset_file(room_id, str(p['asset_id']))
            if f is not None:
                st = f.stat()
                p = {**p, 'src': f"{media_url(room_id, str(p['asset_id']))}&v={st.st_size:x}-{st.st_mtime_ns:x}"}
        out.append(p)
    return {**doc, 'parts': out}


def asset_file(room_id: str, asset_id: str) -> Path | None:
    par = _par()
    a = next((a for a in par._read_assets(room_id) if str(a.get('id')) == str(asset_id)), None)
    if not a or not a.get('local_path'):
        return None
    p = Path(par.local_file(str(a['local_path'])))
    return p if p.exists() else None


# ── 描く（エディターと同じ描き方） ───────────────────────────────────────────────

def render(room_id: str, content_id: str, out: Path | None = None, marks: list | None = None,
           out_w: int = 1280, doc: dict[str, Any] | None = None, timeout: float = 120) -> Path:
    doc = versioned(room_id, doc or get(room_id, content_id))
    if not doc.get('parts'):
        raise ValueError('サムネに部品がありません')
    d = _par()._room_dir(room_id) / 'thumbnails' / content_id
    d.mkdir(parents=True, exist_ok=True)
    out = Path(out or d / f"render_{int(time.time() * 1000)}.png")
    spec = d / f"spec_{uuid.uuid4().hex[:8]}.json"
    spec.write_text(json.dumps({'doc': doc, 'marks': marks or [], 'outW': out_w, 'out': str(out),
                                'web_base': os.environ.get('DAN_THUMB_RENDER_BASE') or 'http://127.0.0.1:3000'},
                               ensure_ascii=False), encoding='utf-8')
    try:
        r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'render_thumbnail.py'), str(spec)],
                           capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
    finally:
        spec.unlink(missing_ok=True)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"サムネを描けませんでした: {(r.stderr or r.stdout)[-600:]}")
    return out


def export(room_id: str, content_id: str) -> dict[str, Any]:
    """1280×720 の PNG に書き出し、作品の outputs に残す。{path, url, rev}"""
    from app.services.timeline_draft import ContentsLock
    par = _par()
    doc = get(room_id, content_id)
    d = par._room_dir(room_id) / 'thumbnails' / content_id
    out = render(room_id, content_id, d / f"export_rev{doc.get('rev') or 0}.png", doc=doc)
    latest = d / 'export.png'
    latest.write_bytes(out.read_bytes())
    # チャット・ほかの画面で開ける場所（/api/v1/files/）にも置く
    files = getattr(par, 'UPLOADS_DIR', None)
    url = None
    if files is not None:
        name = f"thumb-{content_id[:8]}-rev{doc.get('rev') or 0}.png"
        (Path(files) / name).write_bytes(out.read_bytes())
        url = f"/api/v1/files/{name}"
    with ContentsLock(room_id):
        contents = par._read_contents(room_id)
        c = next((c for c in contents if str(c.get('id')) == str(content_id)), None)
        if c is not None:
            outs = [o for o in (c.get('outputs') or []) if isinstance(o, dict) and o.get('kind') != 'thumbnail_png']
            outs.append({'kind': 'thumbnail_png', 'path': str(latest), 'url': url, 'rev': doc.get('rev'), 'created_at': _now()})
            c['outputs'] = outs
            par._write_contents(room_id, contents)
    return {'path': str(latest), 'url': url, 'rev': doc.get('rev')}


def cover(room_id: str, content_id: str) -> Path | None:
    """作品の一覧の絵。今の形の書き出しがあればそれ、無ければ描く。"""
    doc = get(room_id, content_id)
    if not doc.get('parts'):
        return None
    d = _par()._room_dir(room_id) / 'thumbnails' / content_id
    p = d / f"cover_rev{doc.get('rev') or 0}.png"
    if not p.exists():
        for old in d.glob('cover_rev*.png'):
            old.unlink(missing_ok=True)
        render(room_id, content_id, p, out_w=640, doc=doc)
    return p


# ── 指した範囲だけを描き直す ─────────────────────────────────────────────────────

def _api_size(w: float, h: float, long_side: int = 1536) -> tuple[int, int]:
    """gpt-image に渡せる大きさ（両辺16の倍数・総画素 655,360 以上・縦横比 3 以内）。"""
    r = max(1 / 3, min(3, w / max(1, h)))
    if r >= 1:
        W, H = long_side, long_side / r
    else:
        W, H = long_side * r, long_side
    k = 1.0
    while (round(W * k / 16) * 16) * (round(H * k / 16) * 16) < 655360:
        k *= 1.05
    return int(round(W * k / 16) * 16), int(round(H * k / 16) * 16)


def repaint(room_id: str, content_id: str, part_id: str, box: tuple[float, float, float, float], prompt: str,
            quality: str = 'high', feather: int = 6, masked: bool = False) -> dict[str, Any]:
    """絵の部品 part_id の、サムネの座標の範囲 box=(x, y, w, h) だけを描き直す。範囲の外は元の画素のまま。

    元の絵は消さずに残し（新しい素材を作って部品の絵を差し替える）、前の形は履歴に入るので undo で戻せる。"""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    import numpy as np

    doc = get(room_id, content_id)
    part = next((p for p in doc.get('parts') or [] if p.get('id') == part_id), None)
    if not part or part.get('type') != 'image':
        raise ValueError('描き直す絵の部品が見つかりません（文字の部品は文字・色の数値を直す）')
    if part.get('rotation'):
        raise ValueError('回した絵は描き直せません。回転を0に戻してから描き直します')
    src = asset_file(room_id, str(part.get('asset_id') or ''))
    if src is None:
        raise ValueError('部品の元の絵のファイルが見つかりません')
    im = Image.open(src).convert('RGBA')
    iw, ih = im.size
    sx, sy = iw / float(part['w']), ih / float(part['h'])
    bx, by, bw, bh = box
    if part.get('flip_x'):
        bx = float(part['x']) + float(part['w']) - (bx - float(part['x'])) - bw
    x0 = max(0, int(math.floor((bx - float(part['x'])) * sx)))
    y0 = max(0, int(math.floor((by - float(part['y'])) * sy)))
    x1 = min(iw, int(math.ceil((bx + bw - float(part['x'])) * sx)))
    y1 = min(ih, int(math.ceil((by + bh - float(part['y'])) * sy)))
    if x1 - x0 < 8 or y1 - y0 < 8:
        raise ValueError('範囲がその絵の外か、小さすぎます')
    # 周りも見せて描かせる（つながりが自然になるように）。範囲の幅の 40% ずつ外へ
    mx, my = int((x1 - x0) * 0.4) + 32, int((y1 - y0) * 0.4) + 32
    cx0, cy0, cx1, cy1 = max(0, x0 - mx), max(0, y0 - my), min(iw, x1 + mx), min(ih, y1 + my)
    crop = im.crop((cx0, cy0, cx1, cy1))
    aw, ah = _api_size(cx1 - cx0, cy1 - cy0)
    work = _par()._room_dir(room_id) / 'thumbnails' / content_id / f"repaint_{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    bg = Image.new('RGB', crop.size, (128, 128, 128))
    bg.paste(crop, mask=crop.getchannel('A'))
    bg.resize((aw, ah), Image.LANCZOS).save(work / 'in.png')
    mask = Image.new('RGBA', (aw, ah), (0, 0, 0, 255))
    kx, ky = aw / (cx1 - cx0), ah / (cy1 - cy0)
    ImageDraw.Draw(mask).rectangle([(x0 - cx0) * kx, (y0 - cy0) * ky, (x1 - cx0) * kx, (y1 - cy0) * ky], fill=(0, 0, 0, 0))
    mask.save(work / 'mask.png')
    # 既定はマスクを付けずに写真全体を渡し、頼まれた所だけを変えた写真を返してもらう（マスクで塗り直させると、
    # 顔立ちやメガネの色まで別人に変わった。2026-11-18 の試し）。使うのは範囲の中だけなので、外は元のまま。
    keep = "写っている人や物は、同じ人・同じ物のまま描く（顔立ち・年齢・髪型・メガネの形と色・服を変えない）。"
    if masked:
        full_prompt = (f"{prompt}\n\n透明にした範囲（マスク）の中だけを描き直す。範囲の外は元の絵のまま。{keep}"
                       "頼まれた所だけを変える。写真の質感・光・色合いを周りに合わせ、境目が分からないようにつなぐ。文字・ロゴ・透かしは描かない。")
    else:
        full_prompt = (f"この写真を編集する: {prompt}\n\n頼まれた所（表情・しぐさ・足す物・消す物）だけを変え、それ以外は元の写真と"
                       f"同じ構図・同じ位置・同じ大きさのまま描く。{keep}写真の質感・光・色合いも元のまま。文字・ロゴ・透かしは描かない。")
    (work / 'prompt.txt').write_text(full_prompt, encoding='utf-8')
    cmd = [sys.executable, str(ROOT / 'scripts' / 'gpt_image.py'), '--image', str(work / 'in.png'),
           '--size', f"{aw}x{ah}", '--quality', quality, '--out', str(work / 'out.png')]
    if masked:
        cmd[4:4] = ['--mask', str(work / 'mask.png')]
    r = subprocess.run(cmd, input=full_prompt, capture_output=True, text=True, timeout=600, cwd=str(ROOT))
    if r.returncode != 0 or not (work / 'out.png').exists():
        raise RuntimeError(f"描き直せませんでした: {(r.stderr or r.stdout)[-500:]}")
    gen = Image.open(work / 'out.png').convert('RGB').resize(crop.size, Image.LANCZOS)
    # 範囲の内側だけを、縁を少しぼかして元の絵に重ねる。範囲の外は元の画素のまま
    m = Image.new('L', crop.size, 0)
    f = max(0, min(feather, (x1 - x0) // 4, (y1 - y0) // 4))
    ImageDraw.Draw(m).rectangle([x0 - cx0 + f, y0 - cy0 + f, x1 - cx0 - f - 1, y1 - cy0 - f - 1], fill=255)
    if f:
        m = m.filter(ImageFilter.GaussianBlur(f / 2))
        inner = Image.new('L', crop.size, 0)
        ImageDraw.Draw(inner).rectangle([x0 - cx0, y0 - cy0, x1 - cx0 - 1, y1 - cy0 - 1], fill=255)
        m = ImageChops.multiply(m, inner)
    patched = crop.copy()
    gen_rgba = gen.convert('RGBA')
    gen_rgba.putalpha(crop.getchannel('A'))   # 透明な所（切り抜いた人の外）はそのまま
    patched = Image.composite(gen_rgba, patched, m)
    new = im.copy()
    new.paste(patched, (cx0, cy0))
    # 範囲の外が1画素も変わっていないことを確かめる
    a, b = np.asarray(im), np.asarray(new)
    outside = np.ones(a.shape[:2], bool)
    outside[y0:y1, x0:x1] = False
    if not np.array_equal(a[outside], b[outside]):
        raise RuntimeError('範囲の外が変わってしまったので、描き直しを使いません')
    out = work.parent / f"{part_id}_{int(time.time())}.png"
    new.save(out)
    asset = add_image_asset(room_id, out, f"サムネ {part.get('name') or part_id} 描き直し.png")
    parts = [dict(p) for p in doc['parts']]
    for p in parts:
        if p.get('id') == part_id:
            p['src'] = media_url(room_id, asset['id'])
            p['asset_id'] = asset['id']
    saved = save(room_id, content_id, {**doc, 'parts': parts}, 'dan')
    return {'part_id': part_id, 'asset_id': asset['id'], 'image': str(out), 'rev': saved['rev'],
            'box_in_image': [x0, y0, x1, y1]}


# ── 荒く並べた絵を「仕上げ」る ────────────────────────────────────────────────────
# 2026-11-18 本人「うん」（機能3「素材を荒く並べて『仕上げ』を押すと、並べた構図のまま光や影を整えた1枚にする」）。
# 仕上げるのは「文字より奥にある絵」（背景・人物・物）だけ。文字と、文字より手前の絵（矢印・× など）は部品のまま残る。
# 結果は1枚の絵の部品「仕上げた絵」になり、元の絵の部品は消さずに隠す（仕上げを外すと元に戻る）。
# 本人が前後を見比べて採用するまで、サムネの形は変えない（採用はエディターが commit するので Ctrl+Z で戻る）。
# 顔: AI が光を整えた絵の、顔の範囲だけ「明るさと色は AI の絵・目鼻立ちの細かい形は元の写真」に合わせ直すので、
# 顔立ちは変わらない（2026-11-18 の試しで AI は人の位置・大きさを1画素も動かさなかった。動いた時は合わせ直さず止める）。

FINISH_PROMPT = """このYouTubeのサムネイル用の合成写真を、1枚の自然な写真に仕上げる。

- 構図はそのまま: 人や物の位置・大きさ・向き・ポーズを変えない。新しい人や物を足さない・消さない・動かさない。
- 写っている人は同じ人のまま: 顔立ち・表情・年齢・髪型・メガネの形と色・服を変えない。
- 整えるのは、光の向きと色・影・色味・つなぎ目だけ: 人と背景の光と色合いをそろえ、人の後ろや足元に自然な影を落とし、切り抜きの縁・ぼかしの帯・境目が分からないように馴染ませる。不自然に途切れた体や机は、同じ位置のまま自然につなぐ。
- 背景の中身（画面・部屋・物）は残し、同じ物のまま光と色だけ合わせる。
- 文字・ロゴ・透かし・枠は描かない（文字はあとで上に重ねる）。
- サムネイルらしく、人がはっきり見える明るさとコントラストにする。"""


def _finish_dir(room_id: str, content_id: str) -> Path:
    d = _par()._room_dir(room_id) / 'thumbnails' / content_id / 'finish'
    d.mkdir(parents=True, exist_ok=True)
    return d


def finish_sources(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """仕上げる絵の部品（奥から手前の順）。一番奥の文字より奥にある、見えている絵。
    もう仕上げてある時は、その仕上げの元の絵（隠してある）を使い、仕上げた絵そのものは使わない（重ねがけしない）。"""
    parts = [p for p in doc.get('parts') or [] if isinstance(p, dict)]
    fin = next((p for p in parts if p.get('type') == 'image' and isinstance(p.get('finish'), dict)), None)
    fin_src = set((fin or {}).get('finish', {}).get('sources') or []) if fin else set()
    first_text = next((i for i, p in enumerate(parts) if p.get('type') == 'text' and not p.get('hidden')), len(parts))
    out = []
    for p in parts[:first_text]:
        if p.get('type') != 'image' or p is fin:
            continue
        if p.get('hidden') and p.get('id') not in fin_src:
            continue
        out.append({**p, 'hidden': False})
    return out


def _finish_write(path: Path, st: dict[str, Any]) -> dict[str, Any]:
    st = {**st, 'updated_at': _now()}
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(st, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)
    return st


def finish_status(room_id: str, content_id: str, job_id: str | None = None) -> dict[str, Any] | None:
    d = _finish_dir(room_id, content_id)
    if not job_id:
        lp = d / 'latest.txt'
        if not lp.exists():
            return None
        job_id = lp.read_text(encoding='utf-8').strip()
    p = d / f"{job_id}.json"
    if not p.exists():
        return None
    st = json.loads(p.read_text(encoding='utf-8'))
    # 本体が途中で入れ替わって裏の仕事が消えた時は、いつまでも「仕上げ中」にしない
    if st.get('state') == 'running' and time.time() - float(st.get('started_ts') or 0) > 900:
        st = _finish_write(p, {**st, 'state': 'error', 'message': '仕上げが途中で止まりました。もう一度押してください'})
    return st


def finish_decide(room_id: str, content_id: str, job_id: str, adopted: bool) -> dict[str, Any]:
    p = _finish_dir(room_id, content_id) / f"{job_id}.json"
    if not p.exists():
        raise ValueError('その仕上げが見つかりません')
    st = json.loads(p.read_text(encoding='utf-8'))
    return _finish_write(p, {**st, 'decided': 'adopted' if adopted else 'discarded'})


def finish_start(room_id: str, content_id: str, note: str = '', quality: str = 'high') -> dict[str, Any]:
    """仕上げを裏で始める。すぐに状態（job_id）を返し、画面は finish_status を読み直して待つ（約1〜2分）。"""
    import threading
    doc = get(room_id, content_id)
    sources = finish_sources(doc)
    if not sources:
        raise ValueError('仕上げる絵がありません（文字より奥に絵の部品を置いてください）')
    cur = finish_status(room_id, content_id)
    if cur and cur.get('state') == 'running':
        return cur
    job_id = f"fin_{int(time.time())}_{uuid.uuid4().hex[:4]}"
    d = _finish_dir(room_id, content_id)
    path = d / f"{job_id}.json"
    st = _finish_write(path, {'job_id': job_id, 'state': 'running', 'step': '絵を並べた形を描いています',
                              'note': note, 'rev': doc.get('rev'), 'sources': [p['id'] for p in sources],
                              'started_at': _now(), 'started_ts': time.time()})
    (d / 'latest.txt').write_text(job_id, encoding='utf-8')

    def run() -> None:
        try:
            res = _finish_run(room_id, content_id, doc, sources, d / job_id, note, quality,
                              lambda step: _finish_write(path, {**json.loads(path.read_text(encoding='utf-8')), 'step': step}))
            _finish_write(path, {**json.loads(path.read_text(encoding='utf-8')), **res, 'state': 'done', 'step': ''})
        except Exception as exc:   # 画面にそのまま出すので、日本語の一文にする
            msg = str(exc) if any('぀' <= ch <= 'ヿ' for ch in str(exc)) else '仕上げに失敗しました。もう一度押してください'
            _finish_write(path, {**json.loads(path.read_text(encoding='utf-8')), 'state': 'error', 'message': msg[:300]})

    threading.Thread(target=run, name=f"thumb-finish-{content_id[:8]}", daemon=True).start()
    return st


def _finish_run(room_id: str, content_id: str, doc: dict[str, Any], sources: list[dict[str, Any]], work: Path,
                note: str, quality: str, step) -> dict[str, Any]:
    from PIL import Image
    work.mkdir(parents=True, exist_ok=True)
    W, H = int(doc.get('width') or 1920), int(doc.get('height') or 1080)
    src_doc = {**doc, 'parts': sources, 'instructions': []}
    render(room_id, content_id, work / 'in.png', out_w=W, doc=src_doc, timeout=240)
    step('AIで光と影を整えています（1〜2分）')
    aw, ah = _api_size(W, H, long_side=2048)
    prompt = FINISH_PROMPT + (f"\n\n本人からの一言: {note}" if note.strip() else '')
    (work / 'prompt.txt').write_text(prompt, encoding='utf-8')
    r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'gpt_image.py'), '--image', str(work / 'in.png'),
                        '--size', f"{aw}x{ah}", '--quality', quality, '--out', str(work / 'ai.png')],
                       input=prompt, capture_output=True, text=True, timeout=900, cwd=str(ROOT))
    if r.returncode != 0 or not (work / 'ai.png').exists():
        raise RuntimeError(f"AI の仕上げに失敗しました: {(r.stderr or r.stdout)[-300:]}")
    step('顔を元の顔に合わせています')
    before = Image.open(work / 'in.png').convert('RGB')
    if before.size != (W, H):
        before = before.resize((W, H), Image.LANCZOS)
    ai = Image.open(work / 'ai.png').convert('RGB').resize((W, H), Image.LANCZOS)
    out, faces = keep_faces(before, ai)
    out.save(work / 'out.png')
    asset = add_image_asset(room_id, work / 'out.png', f"サムネ 仕上げた絵 {time.strftime('%m%d-%H%M')}.png",
                            generated_by='dan:thumbnail-finish')
    return {'asset_id': asset['id'], 'src': media_url(room_id, asset['id']), 'width': W, 'height': H, 'faces': faces}


def keep_faces(before, ai):
    """AI の絵の顔の範囲を、元の写真の目鼻立ち（細かい形）＋AI の絵の明るさと色に合わせ直す。
    返り値 (絵, 顔ごとの記録)。AI が顔を動かした（元の位置で形が合わない）顔は合わせ直さず記録だけ残す。"""
    import cv2
    import numpy as np
    from PIL import Image
    a = cv2.cvtColor(np.asarray(before), cv2.COLOR_RGB2BGR)
    b = cv2.cvtColor(np.asarray(ai), cv2.COLOR_RGB2BGR)
    g = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    found = []
    # 見落としを減らすため、正面2種と横顔（左右）で探す。顔でない所を拾っても、そこは元の写真の細かい形に戻るだけ
    ms = max(32, W // 40)
    for name, flip in (('haarcascade_frontalface_default.xml', False), ('haarcascade_frontalface_alt2.xml', False),
                       ('haarcascade_profileface.xml', False), ('haarcascade_profileface.xml', True)):
        c = cv2.CascadeClassifier(cv2.data.haarcascades + name)
        for (x, y, w, h) in c.detectMultiScale(cv2.flip(g, 1) if flip else g, 1.05, 5, minSize=(ms, ms)):
            if flip:
                x = W - x - w
            if not any(abs(x - fx) < max(w, fw) * 0.5 and abs(y - fy) < max(h, fh) * 0.5 for fx, fy, fw, fh in found):
                found.append((int(x), int(y), int(w), int(h)))
    out = b.astype(np.float32)
    log = []
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    for (x, y, w, h) in found:
        # 元の顔が AI の絵のどこにあるか（同じ位置なら動いていない）
        pad = int(w * 0.12)
        X0, Y0, X1, Y1 = max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + h + pad)
        m = cv2.matchTemplate(gb[Y0:Y1, X0:X1], g[y:y + h, x:x + w], cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(m)
        dx, dy = loc[0] + X0 - x, loc[1] + Y0 - y
        rec = {'box': [x, y, w, h], 'match': round(float(score), 3), 'shift': [int(dx), int(dy)]}
        if score < 0.6 or abs(dx) > w * 0.06 or abs(dy) > h * 0.06:
            rec['kept'] = False
            log.append(rec)
            continue
        # 顔より少し広い楕円の中で、細かい形（元の写真 − ぼかした元の写真）を AI の絵のぼかしに足す
        ex, ey, ew, eh = x - int(w * 0.18), y - int(h * 0.22), int(w * 1.36), int(h * 1.5)
        ex0, ey0, ex1, ey1 = max(0, ex), max(0, ey), min(W, ex + ew), min(H, ey + eh)
        mask = np.zeros((H, W), np.float32)
        cv2.ellipse(mask, (x + w // 2, y + int(h * 0.55)), (int(ew * 0.5), int(eh * 0.5)), 0, 0, 360, 1.0, -1)
        mask = cv2.GaussianBlur(mask, (0, 0), w * 0.06)
        sig = max(2.0, w * 0.035)
        sa = a[ey0:ey1, ex0:ex1].astype(np.float32)
        sb = b[ey0 + dy:ey1 + dy, ex0 + dx:ex1 + dx].astype(np.float32) if (dx or dy) else b[ey0:ey1, ex0:ex1].astype(np.float32)
        if sb.shape != sa.shape:
            rec['kept'] = False
            log.append(rec)
            continue
        detail = sa - cv2.GaussianBlur(sa, (0, 0), sig)
        merged = np.clip(cv2.GaussianBlur(sb, (0, 0), sig) + detail, 0, 255)
        mm = mask[ey0:ey1, ex0:ex1][..., None]
        region = out[ey0:ey1, ex0:ex1]
        out[ey0:ey1, ex0:ex1] = region * (1 - mm) + merged * mm
        rec['kept'] = True
        log.append(rec)
    res = Image.fromarray(cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB))
    return res, log


def apply_finish(doc: dict[str, Any], st: dict[str, Any]) -> dict[str, Any]:
    """仕上げた絵をサムネの形に入れる（エディターの「採用」と同じ。ダンの道具が使う）。
    元の絵の部品は隠すだけ。前の仕上げがあれば外してから入れる。"""
    doc = remove_finish(doc)
    parts = [dict(p) for p in doc.get('parts') or []]
    srcs = set(st.get('sources') or [])
    idx = min([i for i, p in enumerate(parts) if p.get('id') in srcs] or [0])
    for p in parts:
        if p.get('id') in srcs:
            p['hidden'] = True
    parts.insert(idx, {'id': f"f_{uuid.uuid4().hex[:6]}", 'type': 'image', 'name': '仕上げた絵', 'src': st['src'],
                       'asset_id': st['asset_id'], 'x': 0, 'y': 0, 'w': doc.get('width') or 1920, 'h': doc.get('height') or 1080,
                       'locked': True, 'finish': {'job_id': st.get('job_id'), 'sources': sorted(srcs)}})
    return {**doc, 'parts': parts}


def remove_finish(doc: dict[str, Any]) -> dict[str, Any]:
    """仕上げた絵を外し、隠していた元の絵の部品を出す。"""
    parts = [dict(p) for p in doc.get('parts') or []]
    fin = next((p for p in parts if p.get('type') == 'image' and isinstance(p.get('finish'), dict)), None)
    if not fin:
        return doc
    srcs = set(fin['finish'].get('sources') or [])
    parts = [p for p in parts if p is not fin]
    for p in parts:
        if p.get('id') in srcs:
            p['hidden'] = False
    return {**doc, 'parts': parts}
