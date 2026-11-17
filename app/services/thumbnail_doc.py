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


def create(room_id: str, title: str, doc: dict[str, Any], asset_ids: list[str] | None = None) -> dict[str, Any]:
    from app.services.timeline_draft import ContentsLock
    par = _par()
    now = _now()
    content = {
        'id': str(uuid.uuid4()), 'room_id': room_id, 'title': title, 'format': FORMAT, 'status': 'draft',
        'asset_ids': list(asset_ids or []), 'timeline': {'thumbnail': {**doc, 'rev': 1}}, 'outputs': [],
        'created_at': now, 'updated_at': now,
    }
    with ContentsLock(room_id):
        contents = par._read_contents(room_id)
        contents.append(content)
        par._write_contents(room_id, contents)
    return content


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
    doc = doc or get(room_id, content_id)
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
            quality: str = 'high', feather: int = 6) -> dict[str, Any]:
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
    full_prompt = (f"{prompt}\n\n透明にした範囲（マスク）の中だけを描き直す。範囲の外は元の絵のまま。写真の質感・光・色合いを周りに合わせ、"
                   "境目が分からないようにつなぐ。文字・ロゴ・透かしは描かない。")
    (work / 'prompt.txt').write_text(full_prompt, encoding='utf-8')
    r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'gpt_image.py'), '--image', str(work / 'in.png'),
                        '--mask', str(work / 'mask.png'), '--size', f"{aw}x{ah}", '--quality', quality,
                        '--out', str(work / 'out.png')], input=full_prompt, capture_output=True, text=True, timeout=600,
                       cwd=str(ROOT))
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
