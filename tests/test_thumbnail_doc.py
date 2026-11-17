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
