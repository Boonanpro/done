"""エディターのタイムラインに直接書いた指示（ピン・ペン・枠・素材の枠）を、送った時からダンに動かせる。

2026-11-14 本人「チャットで言うほどでもない細かい部分をタイムラインに直接書き込みたい。いちいちチャットに送らなくても、
送信されたタイミングから実行が順次始まっていく。別々に始まるけど、エディターの中のダンは全体の履歴や今何をやって
いるかを把握している」。

指示1つ = 作品の部屋（エディターの右の「ダンと制作」、app/services/editor_rooms.py）の並行作業1つ
（app/services/parallel_job_runner.py）。並行作業は部屋の会話を引き継いで始まり、終わると部屋のダンが起こされて
本人に1通だけ返事を書く。指示の画面上の印（ピンの点・ペンの線・枠）は、その時刻の完成画面に描いた絵にして渡す。

効果音の一覧（sfx_library / use_sfx）も同じ所に置く: 本人「よく使う効果音を一覧にして、自分で手動で貼れるように」。
"""
from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KIND_LABEL = {
    'marker': 'ピン（画面の1点）',
    'freehand': 'ペンで描いた線',
    'rect': '枠で囲んだ範囲',
    'note': '素材の枠（タイムラインの区間）',
}


def _fmt(t: float) -> str:
    t = max(0.0, float(t or 0))
    m = int(t // 60)
    return f"{m}:{t - m * 60:04.1f}"


def _content(room_id: str, content_id: str) -> dict[str, Any] | None:
    from app.api import production_asset_routes as par
    return next((c for c in par._read_contents(room_id) if str(c.get('id')) == str(content_id)), None)


def _shape_text(ann: dict[str, Any]) -> str:
    kind = str(ann.get('kind') or '')
    data = ann.get('data') if isinstance(ann.get('data'), dict) else {}
    pct = lambda v: f"{float(v or 0) * 100:.0f}%"  # noqa: E731
    if kind == 'marker' and isinstance(data.get('point'), dict):
        p = data['point']
        return f"画面の左から{pct(p.get('x'))}・上から{pct(p.get('y'))}の点"
    if kind == 'rect':
        return (f"画面の左{pct(data.get('x'))}・上{pct(data.get('y'))}から、幅{pct(data.get('width'))}・"
                f"高さ{pct(data.get('height'))}の枠")
    if kind == 'freehand' and isinstance(data.get('points'), list) and data['points']:
        xs = [float(p.get('x', 0)) for p in data['points'] if isinstance(p, dict)]
        ys = [float(p.get('y', 0)) for p in data['points'] if isinstance(p, dict)]
        if xs and ys:
            return (f"画面の左{pct(min(xs))}〜{pct(max(xs))}・上{pct(min(ys))}〜{pct(max(ys))}にペンで描いた線"
                    "（形は添付の絵の赤い線）")
    return ''


def _draw_marks(src: Path, dest: Path, ann: dict[str, Any]) -> bool:
    """完成画面の絵に、本人が置いた印（点・線・枠）を赤で描く。"""
    from PIL import Image, ImageDraw
    img = Image.open(src).convert('RGB')
    w, h = img.size
    d = ImageDraw.Draw(img)
    lw = max(3, round(min(w, h) / 160))
    data = ann.get('data') if isinstance(ann.get('data'), dict) else {}
    kind = str(ann.get('kind') or '')
    red = (255, 40, 40)
    if kind == 'marker' and isinstance(data.get('point'), dict):
        x, y = float(data['point'].get('x', 0)) * w, float(data['point'].get('y', 0)) * h
        r = max(10, round(min(w, h) / 40))
        d.ellipse([x - r, y - r, x + r, y + r], outline=red, width=lw)
        d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=red)
    elif kind == 'rect':
        x, y = float(data.get('x', 0)) * w, float(data.get('y', 0)) * h
        d.rectangle([x, y, x + float(data.get('width', 0)) * w, y + float(data.get('height', 0)) * h], outline=red, width=lw)
    elif kind == 'freehand' and isinstance(data.get('points'), list):
        pts = [(float(p.get('x', 0)) * w, float(p.get('y', 0)) * h) for p in data['points'] if isinstance(p, dict)]
        if len(pts) > 1:
            d.line(pts, fill=red, width=lw, joint='curve')
    else:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)
    return True


def frame_with_marks(room_id: str, content_id: str, ann: dict[str, Any]) -> str | None:
    """その時刻の完成画面（カット・テロップ・重ねた絵を反映）に印を描いた PNG の場所。描けなければ None。"""
    kind = str(ann.get('kind') or '')
    if kind not in ('marker', 'rect', 'freehand'):
        return None
    content = _content(room_id, content_id)
    seq = ((content or {}).get('timeline') or {}).get('sequence')
    if not isinstance(seq, dict):
        return None
    from app.api import production_asset_routes as par
    from app.services import sequence_window
    out_dir = par._room_dir(room_id) / 'instructions'
    t = float(ann.get('start') or 0)
    try:
        res = sequence_window.render_frames(room_id, seq, [t], out_dir)
        if not res.get('ok'):
            logger.info('instruction frame not drawn: %s', res.get('error'))
            return None
        raw = Path(res['paths'][0])
        dest = out_dir / f"{ann.get('id') or uuid.uuid4().hex[:8]}.png"
        ok = _draw_marks(raw, dest, ann)
        raw.unlink(missing_ok=True)
        return str(dest) if ok else None
    except Exception:  # noqa: BLE001 — 絵が無くても指示は送る
        logger.exception('instruction frame failed')
        return None


def build_task(ann: dict[str, Any], content_title: str, image: str | None) -> str:
    kind = str(ann.get('kind') or '')
    data = ann.get('data') if isinstance(ann.get('data'), dict) else {}
    start = float(ann.get('start') or 0)
    end = float(ann.get('end') if ann.get('end') is not None else start)
    note = str(ann.get('note') or '').strip()
    lines = [
        f"本人がエディターのタイムラインに直接書き込んだ指示（チャットには書いていない）。作品「{content_title}」のタイムラインで、"
        "この指示のとおりに直す。",
        f"- 種類: {KIND_LABEL.get(kind, kind or '指示')}",
        f"- 場所: {_fmt(start)}〜{_fmt(end)}（タイムラインの {start:.2f}〜{end:.2f} 秒）",
    ]
    shape = _shape_text(ann)
    if shape:
        lines.append(f"- 画面の場所: {shape}")
    if kind == 'note' and data.get('mode') == 'find':
        lines.append(f"- 本人の頼み: この区間（{end - start:.1f}秒）に置く映像を、言葉に合う実物の素材から探して取り込み、"
                     "この区間にぴったり置く（Envato などの素材集・本人の素材フォルダ。AIで作らない）。")
    lines.append(f"- 指示の言葉: 「{note}」" if note else "- 指示の言葉: （無し。印と場所から読み取る）")
    if image:
        lines.append(f"- 印を描いた完成画面の絵: {image}（Read で開ける。赤い印が本人の印）")
    lines += [
        "",
        "同じ作品では、本人が送ったほかの指示もそれぞれ並行で動いている（parallel_work の list で見られる）。"
        "同じクリップを触る作業があれば、相手の結果を壊さないように直す。指示の範囲の外は触らない。",
        "直したら render_frame・probe_audio で実物を確かめる。最後の返事は、本人に見せる言葉で1〜2文（何をどこに入れたか）。",
    ]
    return '\n'.join(lines)


def _title(ann: dict[str, Any]) -> str:
    note = str(ann.get('note') or '').strip().replace('\n', ' ')
    head = {'marker': 'ピン', 'freehand': 'ペン', 'rect': '枠', 'note': '素材の枠'}.get(str(ann.get('kind') or ''), '指示')
    return f"{head} {_fmt(float(ann.get('start') or 0))} {note}"[:40]


async def send(user_id: str, asset_room_id: str, content_id: str, ann: dict[str, Any]) -> dict[str, Any]:
    """指示を1つ、作品の部屋の並行作業として始める。{job_id, room_id, state, image}。"""
    import asyncio
    from app.services import editor_rooms, parallel_job_runner
    content = _content(asset_room_id, content_id)
    if not content:
        raise ValueError('作品が見つかりません')
    room = await editor_rooms.ensure_room(user_id, asset_room_id, content_id)
    image = await asyncio.to_thread(frame_with_marks, asset_room_id, content_id, ann)
    task = build_task(ann, str(content.get('title') or content_id), image)
    job = await parallel_job_runner.start(room['room_id'], user_id, task, title=_title(ann))
    return {'job_id': job['id'], 'room_id': room['room_id'], 'state': job.get('state'), 'image': image}


def states(user_id: str, job_ids: list[str]) -> list[dict[str, Any]]:
    """送った指示の進み具合（エディターのピンの色と一言に使う）。"""
    from app.services import command_job_state as state
    from app.services.parallel_job_runner import public
    out = []
    for jid in job_ids[:100]:
        s = state.read(jid)
        if not s or s.get('user_id') != user_id:
            continue
        p = public(s)
        out.append({'job_id': jid, 'state': p['state'], 'label': p['state_label'], 'active': p['active'],
                    'progress': p['last_progress'], 'result': p['result_excerpt']})
    return out


# ── 効果音の一覧 ──────────────────────────────────────────────────────────────────
# ダンが入れた効果音は、作品の部屋ごとに「SE 〜」という名前の音の素材として登録されている。全部の部屋から集めて
# 名前でまとめ、作品で使われた回数の多い順に並べる。

SFX_PREFIX = 'SE '


def _is_sfx(asset: dict[str, Any]) -> bool:
    return asset.get('kind') == 'audio' and str(asset.get('filename') or '').startswith(SFX_PREFIX)


def sfx_library(room_id: str) -> list[dict[str, Any]]:
    from app.api import production_asset_routes as par
    root = par.ASSET_ROOT
    by_name: dict[str, dict[str, Any]] = {}
    here = {str(a.get('filename')): a for a in par._read_assets(room_id) if _is_sfx(a)}
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []:
        idx = d / 'assets.json'
        if not idx.exists():
            continue
        try:
            rows = json.loads(idx.read_text(encoding='utf-8'))
        except Exception:  # noqa: BLE001
            continue
        sfx = {str(a['id']): a for a in rows if isinstance(a, dict) and _is_sfx(a) and a.get('id')}
        if not sfx:
            continue
        uses: dict[str, int] = {}
        try:
            for c in json.loads((d / 'contents.json').read_text(encoding='utf-8')):
                seq = ((c.get('timeline') or {}).get('sequence') or {}) if isinstance(c, dict) else {}
                for t in seq.get('tracks') or []:
                    for cl in t.get('clips') or []:
                        aid = str(cl.get('asset_id') or '')
                        if aid in sfx:
                            uses[aid] = uses.get(aid, 0) + 1
        except Exception:  # noqa: BLE001
            pass
        for aid, a in sfx.items():
            name = str(a.get('filename'))
            path = Path(par.local_file(str(a.get('local_path') or '')))
            if not path.exists():
                continue
            row = by_name.setdefault(name, {
                'key': f"{d.name}:{aid}", 'name': name[len(SFX_PREFIX):], 'filename': name, 'uses': 0,
                'duration': float((a.get('metadata') or {}).get('duration') or 0),
                'source_room_id': d.name, 'source_asset_id': aid,
            })
            row['uses'] += uses.get(aid, 0)
            if d.name == room_id:   # この作品の部屋に同じ音があれば、そちらを使う
                row.update(key=f"{d.name}:{aid}", source_room_id=d.name, source_asset_id=aid)
    for name, row in by_name.items():
        row['in_room_asset_id'] = str(here[name]['id']) if name in here else None
        row['preview_url'] = (f"/api/v1/production-assets/media?room_id={row['source_room_id']}"
                              f"&asset_id={row['source_asset_id']}&variant=original")
    return sorted(by_name.values(), key=lambda r: (-r['uses'], r['name']))


def use_sfx(room_id: str, source_room_id: str, source_asset_id: str) -> dict[str, Any]:
    """一覧の効果音を、この作品の部屋の素材にする（同じ名前があればそれを返す）。返すのは素材の行。"""
    from app.api import production_asset_routes as par
    src = next((a for a in par._read_assets(source_room_id) if str(a.get('id')) == str(source_asset_id)), None)
    if not src or not _is_sfx(src):
        raise ValueError('効果音が見つかりません')
    rows = par._read_assets(room_id)
    hit = next((a for a in rows if _is_sfx(a) and a.get('filename') == src.get('filename')), None)
    if hit:
        return hit
    if source_room_id == room_id:
        return src
    src_path = Path(par.local_file(str(src.get('local_path') or '')))
    new_id = uuid.uuid4().hex[:12]
    dest = par._room_dir(room_id) / f"sfx_{new_id}{src_path.suffix}"
    shutil.copy2(src_path, dest)
    now = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
    row = {
        'id': new_id, 'room_id': room_id, 'kind': 'audio', 'source_type': 'sfx_library',
        'original_uri': src.get('original_uri') or str(src_path), 'local_path': str(dest),
        'filename': src.get('filename'), 'metadata': dict(src.get('metadata') or {}),
        'status': 'ready', 'created_at': now, 'updated_at': now, 'generated_by': 'owner:sfx_library',
    }
    rows = par._read_assets(room_id)
    rows.append(row)
    par._write_assets(room_id, rows)
    return row


def room_work_text(room_id: str, hours: float = 3.0) -> str:
    """作品の部屋で、本人がタイムラインから送った指示の作業（並行作業）の今の一覧。部屋のダンと各作業の前置きに入れる。
    本人「エディターの中のダンは全体の履歴や今何をやっているかを把握している」。"""
    from datetime import datetime, timedelta, timezone
    from app.services import command_job_state as state
    if not room_id or not state.ROOT.exists():
        return ''
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = []
    for p in state.ROOT.glob('*.json'):
        s = state.read(p.stem)
        if not s or s.get('room_id') != room_id or s.get('engine') not in ('parallel', 'make'):
            continue
        active = s.get('state') not in state.TERMINAL
        if not active and (s.get('updated_at') or '') < since:
            continue
        rows.append(s)
    if not rows:
        return ''
    rows.sort(key=lambda s: s.get('created_at') or '')
    label = {'completed': '済み', 'failed': '止まった', 'cancelled': '取り消し'}
    lines = ['## この作品で並行して動いている作業（本人がタイムラインから送った指示など）',
             'それぞれ別のダンが部屋の会話を引き継いで動かしている。同じクリップを直す時は相手の結果を壊さない。'
             '「今何してる？」には、この一覧と parallel_work の list で答える。']
    for s in rows[-20:]:
        st = '動いている' if s.get('state') not in state.TERMINAL else label.get(s.get('state'), s.get('state'))
        res = str(s.get('result') or s.get('error') or '').strip().replace('\n', ' ')[:160]
        lines.append(f"- [{st}] {s.get('title') or ''}（id {str(s['id'])[:8]}）" + (f" → {res}" if res and st != '動いている' else ''))
    return '\n'.join(lines)
