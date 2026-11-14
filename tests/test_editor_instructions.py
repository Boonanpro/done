"""エディターのタイムラインに書いた指示・効果音の一覧・作品ごとの編集の順番待ち（app/services/editor_instructions.py）。"""
import json
import threading
import time
from pathlib import Path

import pytest


@pytest.fixture
def asset_root(tmp_path, monkeypatch):
    from app.api import production_asset_routes as par
    from app.services import timeline_draft as td
    monkeypatch.setattr(par, 'ASSET_ROOT', tmp_path)
    monkeypatch.setattr(td, 'UPLOAD_ROOT', tmp_path)
    return tmp_path


def _room(root: Path, room: str, assets, contents=()):
    d = root / room
    d.mkdir(parents=True, exist_ok=True)
    (d / 'assets.json').write_text(json.dumps(list(assets), ensure_ascii=False), encoding='utf-8')
    (d / 'contents.json').write_text(json.dumps(list(contents), ensure_ascii=False), encoding='utf-8')
    return d


def _sfx(root, room, aid, name, dur=0.5):
    f = root / room / f'{aid}.wav'
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b'RIFF0000WAVE')
    return {'id': aid, 'kind': 'audio', 'filename': f'SE {name}', 'local_path': str(f), 'metadata': {'duration': dur}}


def test_task_carries_place_shape_words_and_image():
    from app.services.editor_instructions import build_task
    ann = {'id': 'a1', 'kind': 'marker', 'intent': 'comment', 'start': 83.4, 'end': 84.4,
           'note': 'ここに和太鼓のドン', 'data': {'point': {'x': 0.25, 'y': 0.5}}}
    text = build_task(ann, 'スヤさん1本目', '/tmp/x.png')
    assert '1:23.4〜1:24.4' in text and '83.40〜84.40' in text
    assert '左から25%・上から50%' in text
    assert '「ここに和太鼓のドン」' in text and '/tmp/x.png' in text
    find = build_task({'kind': 'note', 'intent': 'generate', 'start': 10, 'end': 15, 'note': '札束',
                       'data': {'mode': 'find'}}, 't', None)
    assert '5.0秒' in find and 'AIで作らない' in find


def test_marks_are_drawn_on_the_frame(tmp_path):
    from PIL import Image
    from app.services.editor_instructions import _draw_marks
    src = tmp_path / 'f.png'
    Image.new('RGB', (320, 180), (0, 0, 0)).save(src)
    out = tmp_path / 'o.png'
    assert _draw_marks(src, out, {'kind': 'freehand', 'data': {'points': [{'x': 0.1, 'y': 0.1}, {'x': 0.9, 'y': 0.9}]}})
    img = Image.open(out)
    assert img.getpixel((160, 90))[0] > 200          # 線の真ん中が赤
    assert not _draw_marks(src, out, {'kind': 'note', 'data': {}})


def test_sfx_library_ranks_by_use_and_prefers_this_room(asset_root):
    a = _sfx(asset_root, 'roomA', 'a1', '和太鼓でドン')
    b = _sfx(asset_root, 'roomA', 'a2', 'シャキーン1')
    seq = {'tracks': [{'id': 't', 'type': 'audio', 'clips': [{'asset_id': 'a2'}, {'asset_id': 'a2'}, {'asset_id': 'a1'}]}]}
    _room(asset_root, 'roomA', [a, b], [{'id': 'c1', 'timeline': {'sequence': seq}}])
    c = _sfx(asset_root, 'roomB', 'b1', '和太鼓でドン')
    _room(asset_root, 'roomB', [c, {'id': 'v', 'kind': 'video', 'filename': 'SE 映像は入れない'}])
    from app.services.editor_instructions import sfx_library
    lib = sfx_library('roomB')
    assert [r['name'] for r in lib] == ['シャキーン1', '和太鼓でドン']
    don = lib[1]
    assert don['in_room_asset_id'] == 'b1' and don['source_room_id'] == 'roomB'
    assert lib[0]['in_room_asset_id'] is None and lib[0]['uses'] == 2


def test_use_sfx_copies_once_into_the_room(asset_root):
    a = _sfx(asset_root, 'roomA', 'a1', 'チリン', 3.1)
    _room(asset_root, 'roomA', [a])
    _room(asset_root, 'roomB', [])
    from app.services.editor_instructions import use_sfx
    row = use_sfx('roomB', 'roomA', 'a1')
    assert row['filename'] == 'SE チリン' and Path(row['local_path']).exists()
    assert Path(row['local_path']).parent == asset_root / 'roomB'
    again = use_sfx('roomB', 'roomA', 'a1')
    assert again['id'] == row['id']
    assert len(json.loads((asset_root / 'roomB' / 'assets.json').read_text())) == 1


def test_content_edit_lock_serialises_two_dans(asset_root):
    from app.services import timeline_draft as td
    (asset_root / 'r').mkdir()
    order = []

    def step(name):
        with td.content_edit_lock('r', 'c1') as got:
            assert got
            order.append(name + '+')
            time.sleep(0.2)
            order.append(name + '-')

    ts = [threading.Thread(target=step, args=(n,)) for n in 'ab']
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert order in (['a+', 'a-', 'b+', 'b-'], ['b+', 'b-', 'a+', 'a-'])
