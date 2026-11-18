"""部品で持つサムネ（app/services/thumbnail_doc.py）: 保存・元に戻す・指した範囲だけの描き直し。"""
import shutil
import subprocess
import uuid
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.api import production_asset_routes as par
from app.services import thumbnail_doc as td


@pytest.fixture()
def room():
    rid = f"pytest-thumb-{uuid.uuid4().hex[:8]}"
    yield rid
    shutil.rmtree(par.ASSET_ROOT / rid, ignore_errors=True)


def _doc(room_id):
    d = par._room_dir(room_id)
    rng = np.random.default_rng(1)
    Image.fromarray(rng.integers(0, 255, (540, 960, 4), dtype=np.uint8)).save(d / 'bg.png')
    a = td.add_image_asset(room_id, d / 'bg.png', 'bg.png')
    return {'width': 1920, 'height': 1080, 'parts': [
        {'id': 'bg', 'type': 'image', 'src': td.media_url(room_id, a['id']), 'asset_id': a['id'], 'x': 0, 'y': 0, 'w': 1920, 'h': 1080},
        {'id': 't1', 'type': 'text', 'text': '先に', 'x': 100, 'y': 900, 'font': 'hiragino-w9', 'size': 168, 'fill': '#ffffff'},
    ]}


def test_save_rev_and_undo(room):
    c = td.create(room, 'サムネ', _doc(room))
    assert td.is_thumbnail(c)
    doc = td.get(room, c['id'])
    doc['parts'][1]['y'] = 700
    saved = td.save(room, c['id'], doc, 'dan')
    assert saved['rev'] == 2 and td.get(room, c['id'])['parts'][1]['y'] == 700
    back = td.undo(room, c['id'])
    assert back['parts'][1]['y'] == 900 and back['rev'] == 3
    with pytest.raises(ValueError):
        td.undo(room, c['id'])


def test_repaint_changes_only_the_box(room, monkeypatch):
    c = td.create(room, 'サムネ', _doc(room))
    real_run = subprocess.run

    def fake_run(cmd, *args, **kw):
        if any(str(x).endswith('gpt_image.py') for x in cmd):
            out = cmd[cmd.index('--out') + 1]
            size = cmd[cmd.index('--size') + 1]
            w, h = (int(v) for v in size.split('x'))
            Image.new('RGB', (w, h), (255, 0, 0)).save(out)
            return subprocess.CompletedProcess(cmd, 0, '', '')
        return real_run(cmd, *args, **kw)

    monkeypatch.setattr(td.subprocess, 'run', fake_run)
    before = np.asarray(Image.open(par._room_dir(room) / 'bg.png').convert('RGBA'))
    res = td.repaint(room, c['id'], 'bg', (400, 200, 300, 200), 'もっと困った顔に')
    after = np.asarray(Image.open(res['image']).convert('RGBA'))
    x0, y0, x1, y1 = res['box_in_image']
    assert (x0, y0, x1, y1) == (200, 100, 350, 200)   # 1920 幅の座標 → 960 幅の絵
    outside = np.ones(before.shape[:2], bool)
    outside[y0:y1, x0:x1] = False
    assert np.array_equal(before[outside], after[outside])
    mid = after[(y0 + y1) // 2, (x0 + x1) // 2]
    assert tuple(mid[:3]) == (255, 0, 0)
    doc = td.get(room, c['id'])
    assert doc['parts'][0]['asset_id'] == res['asset_id'] and doc['rev'] == 2
    assert td.undo(room, c['id'])['parts'][0]['asset_id'] != res['asset_id']


def test_api_size_rules():
    for w, h in [(300, 200), (1920, 1080), (50, 400), (1000, 1000)]:
        aw, ah = td._api_size(w, h)
        assert aw % 16 == 0 and ah % 16 == 0 and aw * ah >= 655360 and max(aw, ah) / min(aw, ah) <= 3.01


# ── 仕上げ（荒く並べた絵を、構図のまま光と影を整えた1枚に） ──

def _finish_doc(room_id):
    d = _doc(room_id)
    d['parts'] = [
        d['parts'][0],
        {'id': 'person', 'type': 'image', 'src': 'x', 'x': 300, 'y': 100, 'w': 600, 'h': 900},
        {'id': 'old', 'type': 'image', 'src': 'x', 'x': 0, 'y': 0, 'w': 10, 'h': 10, 'hidden': True},
        d['parts'][1],
        {'id': 'arrow', 'type': 'image', 'src': 'x', 'x': 1200, 'y': 500, 'w': 200, 'h': 200},
    ]
    return d


def test_finish_sources_are_the_pictures_behind_the_text(room):
    doc = _finish_doc(room)
    assert [p['id'] for p in td.finish_sources(doc)] == ['bg', 'person']   # 隠した絵・文字より手前の矢印は使わない
    st = {'job_id': 'fin_1', 'src': '/m', 'asset_id': 'a1', 'sources': ['bg', 'person']}
    done = td.apply_finish(doc, st)
    ids = [p['id'] for p in done['parts']]
    fin = done['parts'][0]
    assert fin['finish']['sources'] == ['bg', 'person'] and fin['locked'] and (fin['w'], fin['h']) == (1920, 1080)
    assert {p['id']: p.get('hidden') for p in done['parts']}['person'] is True
    assert ids[-2:] == ['t1', 'arrow']                                     # 文字と矢印は部品のまま手前に
    # もう一度仕上げる時は、仕上げた絵ではなく元の絵から（重ねがけしない）
    assert [p['id'] for p in td.finish_sources(done)] == ['bg', 'person']
    again = td.apply_finish(done, {**st, 'job_id': 'fin_2', 'src': '/m2'})
    assert sum(1 for p in again['parts'] if p.get('finish')) == 1
    back = td.remove_finish(again)
    assert [p['id'] for p in back['parts']] == ['bg', 'person', 'old', 't1', 'arrow']
    assert not back['parts'][1].get('hidden') and back['parts'][2]['hidden'] is True


def test_finish_job_runs_and_keeps_the_layout(room, monkeypatch):
    c = td.create(room, 'サムネ', _finish_doc(room))
    rendered = {}

    def fake_render(room_id, content_id, out=None, marks=None, out_w=1280, doc=None, timeout=120):
        rendered['ids'] = [p['id'] for p in doc['parts']]
        Image.new('RGB', (out_w, round(out_w * 1080 / 1920)), (40, 40, 40)).save(out)
        return Path(out)

    def fake_run(cmd, *args, **kw):
        if 'gpt_image.py' in ' '.join(map(str, cmd)):
            out = Path(cmd[cmd.index('--out') + 1])
            w, h = (int(v) for v in cmd[cmd.index('--size') + 1].split('x'))
            assert w % 16 == 0 and h % 16 == 0 and abs(w / h - 16 / 9) < 0.02
            Image.new('RGB', (w, h), (90, 60, 40)).save(out)
            return subprocess.CompletedProcess(cmd, 0, '', '')
        raise AssertionError(cmd)

    monkeypatch.setattr(td, 'render', fake_render)
    monkeypatch.setattr(td.subprocess, 'run', fake_run)
    st = td.finish_start(room, c['id'], 'もっと明るく')
    import time
    for _ in range(100):
        st = td.finish_status(room, c['id'], st['job_id'])
        if st['state'] != 'running':
            break
        time.sleep(0.1)
    assert st['state'] == 'done', st
    assert rendered['ids'] == ['bg', 'person']                       # 文字・矢印は絵に焼かない
    assert 'もっと明るく' in (par._room_dir(room) / 'thumbnails' / c['id'] / 'finish' / st['job_id'] / 'prompt.txt').read_text()
    out = td.asset_file(room, st['asset_id'])
    assert Image.open(out).size == (1920, 1080)
    assert td.get(room, c['id'])['rev'] == 1                          # 採用するまでサムネは変えない
    assert td.finish_status(room, c['id'])['job_id'] == st['job_id']
    assert td.finish_decide(room, c['id'], st['job_id'], True)['decided'] == 'adopted'


def test_keep_faces_without_faces_returns_the_ai_picture():
    a = Image.new('RGB', (320, 180), (10, 10, 10))
    b = Image.new('RGB', (320, 180), (200, 100, 50))
    out, log = td.keep_faces(a, b)
    assert log == [] and np.array_equal(np.asarray(out), np.asarray(b))
