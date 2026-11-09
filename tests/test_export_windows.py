"""The Mac export (FFmpeg path): long timelines are drawn in windows and joined, frame-exact."""
import json
import subprocess
import numpy as np
import pytest
from pathlib import Path
from app.api import production_asset_routes as r

FPS = 30


def _frames(path: Path) -> np.ndarray:
    out = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-vf', 'scale=64:36,format=gray',
                          '-fps_mode', 'passthrough', '-f', 'rawvideo', '-'], capture_output=True, check=True).stdout
    return np.frombuffer(out, np.uint8).reshape(-1, 36, 64).astype(int)


@pytest.fixture
def room(tmp_path, monkeypatch):
    monkeypatch.setattr(r, 'ASSET_ROOT', tmp_path)
    monkeypatch.setattr(r, '_append_job_event', lambda *a, **k: None)
    d = tmp_path / 'room'; d.mkdir()
    src = d / 'src.mp4'   # a counter: every source frame has its own brightness
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'nullsrc=s=64x36:r={FPS}:d=4',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=4',
                    '-vf', 'geq=lum=40+N*1.5:cb=128:cr=128,format=yuv420p', '-color_range', 'tv', '-c:v', 'libx264', '-qp', '0', '-g', '1', '-c:a', 'aac', '-shortest', str(src)], check=True)
    png = d / 'red.png'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=white:s=32x18', '-frames:v', '1', str(png)], check=True)
    assets = [{'id': 'v', 'kind': 'video', 'local_path': str(src), 'metadata': {'duration': 4, 'width': 64, 'height': 36, 'fps': 30, 'has_audio': True}},
              {'id': 'p', 'kind': 'image', 'local_path': str(png), 'metadata': {'width': 32, 'height': 18}}]
    (d / 'assets.json').write_text(json.dumps(assets))
    # Base cut into pieces whose ends are NOT on the frame grid, incl. a one-frame piece; an image
    # overlay and an audio lane on top. 0.0667 / 0.1 / 1.4333 mimic real editor timings.
    cuts = [0, 0.0667, 0.1, 1.4333, 1.4667, 2.5, 3.0]
    base = [{'id': f'b{i}', 'asset_id': 'v', 'timeline_start': a, 'timeline_end': b, 'source_start': a, 'source_end': b}
            for i, (a, b) in enumerate(zip(cuts, cuts[1:]))]
    aud = [{'id': f'a{i}', 'asset_id': 'v', 'timeline_start': c['timeline_start'], 'timeline_end': c['timeline_end'],
            'source_start': c['source_start'], 'source_end': c['source_end'], 'volume': 1} for i, c in enumerate(base)]
    over = [{'id': 'o', 'asset_id': 'p', 'kind': 'image', 'timeline_start': 1.1333, 'timeline_end': 1.3,
             'position': {'x': 0, 'y': 0, 'width': 0.5, 'height': 0.5}}]
    seq = {'format': '16:9', 'frame_rate': FPS, 'tracks': [
        {'id': 'pic', 'type': 'video', 'clips': base}, {'id': 'ov', 'type': 'video', 'clips': over},
        {'id': 'aud', 'type': 'audio', 'clips': aud}]}
    return {'timeline': {'format': '16:9', 'sequence': seq}}


def test_windowed_export_matches_single_pass_frame_for_frame(room, tmp_path, monkeypatch):
    monkeypatch.setattr(r, '_native_export_canvas', lambda fmt: (64, 36))
    monkeypatch.setattr(r, '_add_generated_video_asset', lambda *a, **k: {'id': 'x'})
    monkeypatch.setattr(r, '_attach_output_asset', lambda *a, **k: None)
    monkeypatch.setattr(r, '_read_contents', lambda room_id: [])
    seq = room['timeline']['sequence']
    monkeypatch.setattr(r, '_EXPORT_CHUNK_MIN_CLIPS', 1)
    monkeypatch.setattr(r, '_EXPORT_WINDOW_SEC', 1.0)
    windows = r._export_windows(seq, room)
    assert windows == [(0.0, 1.4333), (1.4333, 2.5), (2.5, 3.0)]   # never inside the overlay (1.13-1.3)
    (tmp_path / 'w').mkdir(); (tmp_path / 's').mkdir()
    chunked = r._render_sequence_job('room', 'w', 'c', room, tmp_path / 'w')
    monkeypatch.setenv('DAN_EXPORT_SINGLE_PASS', '1')
    single = r._render_sequence_job('room', 's', 'c', room, tmp_path / 's')
    a, b = _frames(Path(chunked['output_path'])), _frames(Path(single['output_path']))
    assert len(a) == len(b) == 90                           # 3 s at 30 fps, the one-frame piece included
    assert np.abs(a - b).max() <= 2
    # frame k shows source frame k (the base is a straight run of the source), overlay on 34..38
    src = _frames(tmp_path / 'room' / 'src.mp4')[:90]
    lower = np.abs(a[:, 20:, :] - src[:, 20:, :]).mean((1, 2))
    assert lower.max() < 2, np.nonzero(lower >= 2)
    lit = [k for k in range(90) if a[k, :9, :16].mean() > 200]
    assert lit == list(range(34, 39))
    snd = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=codec_name',
                          '-of', 'csv=p=0', chunked['output_path']], capture_output=True, text=True).stdout.strip()
    assert snd == 'aac'


def _png_gray(path) -> np.ndarray:
    out = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-vf', 'scale=64:36,format=gray',
                          '-f', 'rawvideo', '-'], capture_output=True, check=True).stdout
    return np.frombuffer(out, np.uint8).reshape(36, 64).astype(int)


def _with_pip(room):
    """A video picture-in-picture that starts before the frames looked at (source 2 s ahead)."""
    seq = room['timeline']['sequence']
    pip = {'id': 'pip', 'asset_id': 'v', 'composition': 'pip', 'timeline_start': 0.2, 'timeline_end': 2.9,
           'source_start': 0.9, 'source_end': 3.6, 'position': {'x': 0.5, 'y': 0.5, 'width': 0.5, 'height': 0.5}}
    seq['tracks'].insert(1, {'id': 'pip', 'type': 'video', 'clips': [pip]})
    return room


def test_frame_and_range_render_match_the_whole_export(room, tmp_path, monkeypatch):
    """render_frame on the Mac and watch_render's range export draw only their frames, and each
    frame is the whole export's frame (sources, overlays and a PiP cut mid-clip re-based)."""
    from app.services import sequence_window as sw
    monkeypatch.setenv('DAN_EXPORT_DISABLE_NATIVE', '1')
    monkeypatch.setattr(r, '_native_export_canvas', lambda fmt: (64, 36))
    registered = []
    monkeypatch.setattr(r, '_add_generated_video_asset', lambda *a, **k: registered.append(a) or {'id': 'x'})
    monkeypatch.setattr(r, '_attach_output_asset', lambda *a, **k: None)
    monkeypatch.setattr(r, '_read_contents', lambda room_id: [])
    room = _with_pip(room)
    seq = room['timeline']['sequence']
    (tmp_path / 's').mkdir()
    monkeypatch.setenv('DAN_EXPORT_SINGLE_PASS', '1')
    whole = _frames(Path(r._render_sequence_job('room', 's', 'c', room, tmp_path / 's')['output_path']))
    times = [0.05, 0.6, 1.15, 1.2, 1.45, 2.0, 2.95]
    res = sw.render_frames('room', seq, times, tmp_path / 'frames')
    assert res['ok'], res
    for t, png in zip(times, res['paths']):
        k = sw.frame_of(t, FPS)
        diffs = [np.abs(_png_gray(png) - whole[j]).mean() for j in (k - 1, k, k + 1) if 0 <= j < len(whole)]
        assert np.abs(_png_gray(png) - whole[k]).mean() < 1.5, (t, diffs)
    assert not list((tmp_path / 'frames').glob('*.txt'))   # no scratch left next to the frames
    (tmp_path / 'g').mkdir()
    registered.clear()
    ranged = dict(room, export_ranges=[[0.5, 1.5], [2.0, 2.5]], no_register=True)
    out = r._render_sequence_job('room', 'g', 'c', ranged, tmp_path / 'g')
    got = _frames(Path(out['output_path']))
    assert len(got) == 30 + 15 and not registered
    want = np.concatenate([whole[15:45], whole[60:75]])
    assert np.abs(got - want).mean((1, 2)).max() < 2


def test_cut_caption_keeps_its_animation_phase():
    """A caption cut by a window keeps its own span; its first drawing sits on the export's grid."""
    from app.services import sequence_window as sw
    seq = {'frame_rate': 30, 'tracks': [{'type': 'caption', 'clips': [
        {'id': 'c', 'text': 'x', 'timeline_start': 1.0, 'timeline_end': 4.0, 'style': {'animation': 'pop'}}]}]}
    cut = sw.trim_sequence(seq, {}, 60, 61, 30.0)['tracks'][0]['clips'][0]
    assert cut['_caption_span'] == [1.0, 4.0]
    assert cut['timeline_start'] == 0 and abs(cut['timeline_end'] - 1 / 30) < 1e-9
    # export: drawing i (shown from 1.0 + i/20 - half a frame) at frame 60 (2.0 s) is i = 20
    assert abs(cut['_caption_sample'][0] - 2.0) < 1e-9 and abs(cut['_caption_at']) < 1e-9
    untouched = sw.trim_sequence(seq, {}, 0, 150, 30.0)['tracks'][0]['clips'][0]
    assert '_caption_span' not in untouched and untouched['timeline_start'] == 1.0
