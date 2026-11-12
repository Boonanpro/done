"""The Mac export (FFmpeg path) draws a clip's punch-in box, its colour grade and its moving
box (transform_keys) the way the editor preview does."""
import json
import subprocess

import numpy as np
import pytest
from PIL import Image

from app.api import production_asset_routes as r

FPS = 30
W, H = 160, 90


def _rgb(path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB")).astype(float)


@pytest.fixture
def room(tmp_path, monkeypatch):
    monkeypatch.setattr(r, 'ASSET_ROOT', tmp_path)
    monkeypatch.setattr(r, '_append_job_event', lambda *a, **k: None)
    monkeypatch.setattr(r, '_native_export_canvas', lambda fmt: (W, H))
    monkeypatch.setenv('DAN_EXPORT_DISABLE_NATIVE', '1')
    d = tmp_path / 'room'
    d.mkdir()
    src = d / 'src.mp4'   # a still, detailed, colourful picture (same every frame)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'testsrc2=s={W}x{H}:r={FPS}:d=3',
                    '-vf', 'trim=end_frame=1,loop=loop=-1:size=1,trim=duration=3,setpts=N/(30*TB),format=yuv444p',
                    '-c:v', 'libx264', '-qp', '0', '-g', '1', str(src)], check=True)
    ref = d / 'ref.png'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(src), '-frames:v', '1', str(ref)], check=True)
    assets = [{'id': 'v', 'kind': 'video', 'local_path': str(src),
               'metadata': {'duration': 3, 'width': W, 'height': H, 'fps': FPS, 'has_audio': False}}]
    (d / 'assets.json').write_text(json.dumps(assets))
    return d


def _seq(**props):
    base = {'id': 'b', 'asset_id': 'v', 'timeline_start': 0, 'timeline_end': 2, 'source_start': 0, 'source_end': 2, **props}
    return {'format': '16:9', 'frame_rate': FPS, 'tracks': [{'id': 'pic', 'type': 'video', 'clips': [base]}]}


def _frame(seq, t, tmp_path, name):
    from app.services import sequence_window as sw
    res = sw.render_frames('room', seq, [t], tmp_path / name)
    assert res['ok'], res
    return _rgb(res['paths'][0])


def _zoomed(ref: np.ndarray, x, y, w, h) -> np.ndarray:
    """The preview's drawing of the source in box (x, y, w, h) (canvas fractions, cover)."""
    img = Image.fromarray(ref.astype(np.uint8))
    big = img.resize((round(w * W), round(h * H)), Image.BILINEAR)
    canvas = Image.new('RGB', (W, H))
    canvas.paste(big, (round(x * W), round(y * H)))
    return np.asarray(canvas).astype(float)


def test_full_box_is_only_the_exact_canvas():
    assert r._is_full_box(None) and r._is_full_box({'x': 0, 'y': 0, 'width': 1, 'height': 1})
    assert not r._is_full_box({'x': -0.22, 'y': -0.17, 'width': 1.45, 'height': 1.45})
    assert not r._is_full_box({'x': 0.1, 'y': 0.1, 'width': 0.5, 'height': 0.5})


def test_grade_filter_neutral_and_set():
    assert r._grade_filter({}) == ''
    assert r._grade_filter({'grade': {'ev': 0, 'contrast': 1, 'sat': 1}}) == ''
    f = r._grade_filter({'grade': {'ev': -0.35, 'contrast': 1.18, 'sat': 0.85, 'temp': -0.08}})
    assert f.startswith(',format=rgba') and 'colorchannelmixer' in f and 'lutrgb' not in f
    assert 'lutrgb' in r._grade_filter({'grade': {'ev': 0.5}})


def _native_grade(c: np.ndarray, ev, ct, sat, temp, tint) -> np.ndarray:
    """The native compositor's apply_grade (plain mode), on 0..1 RGB."""
    c = np.clip(c * 2 ** ev, 0, 1)
    c = (c - 0.4135) * ct + 0.4135
    lum = c @ np.array([0.2126, 0.7152, 0.0722])
    c = lum[..., None] + sat * (c - lum[..., None])
    c = c * np.array([1 + 0.22 * temp + 0.10 * tint, 1 - 0.12 * tint, 1 - 0.22 * temp + 0.10 * tint])
    return np.clip(c, 0, 1)


@pytest.mark.parametrize('g', [
    (-0.35, 1.18, 0.85, -0.08, 0.0),
    (0.6, 0.8, 1.4, 0.3, -0.2),
    (0.0, 1.9, 1.9, 0.5, 0.5),     # beyond the mixer's coefficient range: split
])
def test_grade_filter_matches_native_math(tmp_path, g):
    colours = np.array([[x, y, z] for x in (0.1, 0.45, 0.8) for y in (0.05, 0.5, 0.95) for z in (0.2, 0.7)])
    src = (colours * 255).round().astype(np.uint8).reshape(1, -1, 3)
    png = tmp_path / 'c.png'
    Image.fromarray(src).save(png)
    flt = r._grade_filter({'grade': dict(zip(('ev', 'contrast', 'sat', 'temp', 'tint'), g))})
    out = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(png), '-vf', flt.lstrip(',') + ',format=rgb24',
                          '-f', 'rawvideo', '-'], capture_output=True, check=True).stdout
    got = np.frombuffer(out, np.uint8).reshape(-1, 3).astype(float) / 255
    want = _native_grade(src.reshape(-1, 3) / 255, *g)
    assert np.abs(got - want).max() < 0.03, np.abs(got - want).max()


def test_punch_in_box_zooms_the_base_clip(room, tmp_path):
    ref = _rgb(room / 'ref.png')
    box = {'x': -0.22, 'y': -0.17, 'width': 1.45, 'height': 1.45}
    plain = _frame(_seq(), 0.5, tmp_path, 'plain')
    zoom = _frame(_seq(position=box, fit='cover'), 0.5, tmp_path, 'zoom')
    assert np.abs(plain - ref).mean() < 6                     # untouched clip = the source (4:2:0)
    want = _zoomed(ref, -0.22, -0.17, 1.45, 1.45)
    assert np.abs(zoom - want).mean() < 6, np.abs(zoom - want).mean()
    assert np.abs(zoom - plain).mean() > 20                   # visibly different from the original


def test_grade_is_drawn_on_the_base_clip(room, tmp_path):
    ref = _rgb(room / 'ref.png')
    grade = {'ev': -0.35, 'contrast': 1.18, 'sat': 0.85, 'temp': -0.08}
    got = _frame(_seq(grade=grade), 0.5, tmp_path, 'graded')
    want = _native_grade(ref / 255, -0.35, 1.18, 0.85, -0.08, 0.0) * 255
    assert np.abs(got - want).mean() < 5, np.abs(got - want).mean()
    assert got.mean() < ref.mean() - 10                       # darker
    # zoom + grade together
    both = _frame(_seq(grade=grade, position={'x': -0.22, 'y': -0.17, 'width': 1.45, 'height': 1.45}), 0.5, tmp_path, 'both')
    want2 = _native_grade(_zoomed(ref, -0.22, -0.17, 1.45, 1.45) / 255, -0.35, 1.18, 0.85, -0.08, 0.0) * 255
    assert np.abs(both - want2).mean() < 7, np.abs(both - want2).mean()


def test_moving_box_on_a_base_clip(room, tmp_path):
    """transform_keys: a push-in from the full frame (t=0) to 2x on the middle (t=1), held after."""
    ref = _rgb(room / 'ref.png')
    keys = [{'t': 0, 'x': 0, 'y': 0, 'w': 1, 'h': 1}, {'t': 1, 'x': -0.5, 'y': -0.5, 'w': 2, 'h': 2}]
    seq = _seq(transform_keys=keys)
    start = _frame(seq, 0.0, tmp_path, 'k0')
    mid = _frame(seq, 0.5, tmp_path, 'k1')
    end = _frame(seq, 1.5, tmp_path, 'k2')
    assert np.abs(start - ref).mean() < 5
    assert np.abs(end - _zoomed(ref, -0.5, -0.5, 2, 2)).mean() < 7
    want_mid = _zoomed(ref, -0.25, -0.25, 1.5, 1.5)          # frame 15 = halfway
    assert np.abs(mid - want_mid).mean() < 7, np.abs(mid - want_mid).mean()
    # a single key is a static box
    one = _frame(_seq(transform_keys=[{'t': 0, 'x': -0.5, 'y': -0.5, 'w': 2, 'h': 2}]), 0.5, tmp_path, 'k3')
    assert np.abs(one - _zoomed(ref, -0.5, -0.5, 2, 2)).mean() < 7


def test_moving_box_on_an_overlay_video(room, tmp_path):
    """A PiP that slides from the top-left quarter to the bottom-right quarter."""
    seq = _seq(grade={'sat': 0})                               # grey base, colour PiP
    pip = {'id': 'p', 'asset_id': 'v', 'composition': 'pip', 'timeline_start': 0.5, 'timeline_end': 2,
           'source_start': 0, 'source_end': 1.5, 'position': {'x': 0, 'y': 0, 'width': 0.5, 'height': 0.5},
           'transform_keys': [{'t': 0, 'x': 0, 'y': 0, 'w': 1, 'h': 1}, {'t': 1, 'x': 1, 'y': 1, 'w': 1, 'h': 1}]}
    seq['tracks'].append({'id': 'pip', 'type': 'video', 'clips': [pip]})

    def colourful(img, x0, y0):   # mean saturation of a quarter
        q = img[y0:y0 + H // 2, x0:x0 + W // 2]
        return (q.max(-1) - q.min(-1)).mean()
    before = _frame(seq, 0.2, tmp_path, 'o0')
    first = _frame(seq, 0.5, tmp_path, 'o1')
    last = _frame(seq, 1.8, tmp_path, 'o2')
    assert colourful(before, 0, 0) < 5 and colourful(before, W // 2, H // 2) < 5
    assert colourful(first, 0, 0) > 40 and colourful(first, W // 2, H // 2) < 5
    assert colourful(last, W // 2, H // 2) > 40 and colourful(last, 0, 0) < 5


def test_overlay_video_with_a_covering_box_and_grade(room, tmp_path):
    """An upper-lane video whose box covers the canvas is zoomed the same way, and graded."""
    ref = _rgb(room / 'ref.png')
    box = {'x': -0.22, 'y': -0.17, 'width': 1.45, 'height': 1.45}
    grade = {'ev': -0.35, 'contrast': 1.18, 'sat': 0.85, 'temp': -0.08}
    seq = _seq(grade={'sat': 0})
    seq['tracks'].append({'id': 'up', 'type': 'video', 'clips': [
        {'id': 'u', 'asset_id': 'v', 'timeline_start': 0, 'timeline_end': 2, 'source_start': 0, 'source_end': 2,
         'position': box, 'fit': 'cover', 'grade': grade}]})
    got = _frame(seq, 0.5, tmp_path, 'up')
    want = _native_grade(_zoomed(ref, -0.22, -0.17, 1.45, 1.45) / 255, -0.35, 1.18, 0.85, -0.08, 0.0) * 255
    assert np.abs(got - want).mean() < 8, np.abs(got - want).mean()
