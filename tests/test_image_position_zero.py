"""An image whose box starts at x=0 / y=0 is drawn from the canvas corner on the Mac export
and render_frame. `float(pos.get("x") or 0.05)` used to read 0 as "missing" and shifted the
picture 5% right and down."""
import json
import subprocess

import numpy as np
import pytest
from PIL import Image

from app.api import production_asset_routes as r

FPS = 30
W, H = 160, 90


@pytest.fixture
def room(tmp_path, monkeypatch):
    monkeypatch.setattr(r, 'ASSET_ROOT', tmp_path)
    monkeypatch.setattr(r, '_append_job_event', lambda *a, **k: None)
    monkeypatch.setattr(r, '_native_export_canvas', lambda fmt: (W, H))
    monkeypatch.setenv('DAN_EXPORT_DISABLE_NATIVE', '1')
    d = tmp_path / 'room'
    d.mkdir()
    src = d / 'black.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c=black:s={W}x{H}:r={FPS}:d=3',
                    '-c:v', 'libx264', '-qp', '0', str(src)], check=True)
    red = d / 'red.png'
    Image.new('RGB', (W, H), (255, 0, 0)).save(red)
    assets = [{'id': 'v', 'kind': 'video', 'local_path': str(src),
               'metadata': {'duration': 3, 'width': W, 'height': H, 'fps': FPS, 'has_audio': False}},
              {'id': 'img', 'kind': 'image', 'local_path': str(red),
               'metadata': {'width': W, 'height': H}}]
    (d / 'assets.json').write_text(json.dumps(assets))
    return d


def _frame(image_clip, t, tmp_path, name):
    from app.services import sequence_window as sw
    base = {'id': 'b', 'asset_id': 'v', 'timeline_start': 0, 'timeline_end': 2, 'source_start': 0, 'source_end': 2}
    seq = {'format': '16:9', 'frame_rate': FPS, 'tracks': [
        {'id': 'pic', 'type': 'video', 'clips': [base]},
        {'id': 'img', 'type': 'video', 'clips': [image_clip]},
    ]}
    res = sw.render_frames('room', seq, [t], tmp_path / name)
    assert res['ok'], res
    return np.asarray(Image.open(res['paths'][0]).convert('RGB')).astype(float)


def _image(**props):
    return {'id': 'i', 'asset_id': 'img', 'timeline_start': 0, 'timeline_end': 2, **props}


def _is_red(px):
    return px[0] > 200 and px[1] < 60 and px[2] < 60


def test_full_frame_image_at_zero_covers_the_whole_canvas(room, tmp_path):
    got = _frame(_image(position={'x': 0, 'y': 0, 'width': 1, 'height': 1}), 0.5, tmp_path, 'still')
    for y, x in [(0, 0), (0, W - 1), (H - 1, 0), (H - 1, W - 1), (H // 2, W // 2)]:
        assert _is_red(got[y, x]), (y, x, got[y, x])


def test_image_at_zero_with_motion_keys_starts_at_the_corner(room, tmp_path):
    keys = [{'t': 0, 'x': 0, 'y': 0, 'w': 1, 'h': 1}, {'t': 1, 'x': 0, 'y': 0, 'w': 0.5, 'h': 0.5}]
    clip = _image(position={'x': 0, 'y': 0, 'width': 1, 'height': 1}, transform_keys=keys)
    end = _frame(clip, 1.5, tmp_path, 'end')          # held at the last key: top-left quarter
    assert _is_red(end[0, 0]) and _is_red(end[H // 2 - 2, W // 2 - 2])
    assert not _is_red(end[H - 1, W - 1]) and not _is_red(end[H // 2 + 3, W // 2 + 3])
    mid = _frame(clip, 0.5, tmp_path, 'mid')          # moving frame, still anchored at (0, 0)
    assert _is_red(mid[0, 0])


def test_missing_position_keys_keep_their_defaults():
    assert r._box_num({}, 'x', 0.05) == 0.05
    assert r._box_num({'x': None}, 'x', 0.05) == 0.05
    assert r._box_num({'x': 0}, 'x', 0.05) == 0.0
    assert r._box_num({'x': '0'}, 'x', 0.05) == 0.0
    assert r._popout_box_px({'x': 0, 'y': 0, 'width': 1, 'height': 1}, W, H) == (0, 0, W, H)
    assert r._popout_box_px({}, 100, 100) == (27, 84, 46, 14)
