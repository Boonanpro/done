"""The Mac export plays a clip at its own `speed` (2026-11-17: 1.08x clips lost their last words
because the export played them at 1x and cut at the slot length)."""
import json
import subprocess
import numpy as np
import pytest
from pathlib import Path
from app.api import production_asset_routes as r

FPS = 30
SP = 1.25


def _frames(path: Path) -> np.ndarray:
    out = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-vf', 'scale=64:36,format=gray',
                          '-fps_mode', 'passthrough', '-f', 'rawvideo', '-'], capture_output=True, check=True).stdout
    return np.frombuffer(out, np.uint8).reshape(-1, 36, 64).astype(int)


def _loud(path: Path) -> np.ndarray:
    """RMS per 40 ms of the output's sound."""
    pcm = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '1', '-ar', '1000', '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(pcm, np.float32)
    n = len(a) // 40
    return np.sqrt((a[:n * 40].reshape(n, 40) ** 2).mean(1))


@pytest.fixture
def room(tmp_path, monkeypatch):
    monkeypatch.setattr(r, 'ASSET_ROOT', tmp_path)
    monkeypatch.setattr(r, '_append_job_event', lambda *a, **k: None)
    monkeypatch.setattr(r, '_native_export_canvas', lambda fmt: (64, 36))
    monkeypatch.setattr(r, '_add_generated_video_asset', lambda *a, **k: {'id': 'x'})
    monkeypatch.setattr(r, '_attach_output_asset', lambda *a, **k: None)
    monkeypatch.setattr(r, '_read_contents', lambda room_id: [])
    d = tmp_path / 'room'; d.mkdir()
    src = d / 'src.mp4'   # every source frame has its own brightness; sound: tone, silent 2.0-2.4 s, tone to 3.0 s
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'nullsrc=s=64x36:r={FPS}:d=4',
                    '-f', 'lavfi', '-i', "aevalsrc='0.5*sin(2*PI*440*t)*(lt(t,2)+gte(t,2.4)*lt(t,3))':s=48000:d=4",
                    '-vf', 'geq=lum=40+N*1.5:cb=128:cr=128,format=yuv420p', '-color_range', 'tv', '-c:v', 'libx264',
                    '-qp', '0', '-g', '1', '-c:a', 'pcm_s16le', '-shortest', str(src.with_suffix('.mov'))], check=True)
    src = src.with_suffix('.mov')
    assets = [{'id': 'v', 'kind': 'video', 'local_path': str(src),
               'metadata': {'duration': 4, 'width': 64, 'height': 36, 'fps': 30, 'has_audio': True}}]
    (d / 'assets.json').write_text(json.dumps(assets))
    # two pieces at 1.25x: source 0-1.5 → timeline 0-1.2, source 1.5-3.0 → timeline 1.2-2.4
    base = [{'id': 'b0', 'asset_id': 'v', 'timeline_start': 0, 'timeline_end': 1.2, 'source_start': 0, 'source_end': 1.5, 'speed': SP},
            {'id': 'b1', 'asset_id': 'v', 'timeline_start': 1.2, 'timeline_end': 2.4, 'source_start': 1.5, 'source_end': 3.0, 'speed': SP}]
    aud = [dict(c, id='a' + c['id'], volume=1) for c in base]
    seq = {'format': '16:9', 'frame_rate': FPS, 'tracks': [
        {'id': 'pic', 'type': 'video', 'clips': base}, {'id': 'aud', 'type': 'audio', 'clips': aud}]}
    return {'timeline': {'format': '16:9', 'sequence': seq}}


@pytest.mark.parametrize('single', [False, True])
def test_clip_speed_in_picture_and_sound(room, tmp_path, monkeypatch, single):
    if single:
        monkeypatch.setenv('DAN_EXPORT_SINGLE_PASS', '1')
    else:
        monkeypatch.setattr(r, '_EXPORT_CHUNK_MIN_CLIPS', 1)
        monkeypatch.setattr(r, '_EXPORT_WINDOW_SEC', 1.0)
    (tmp_path / 'o').mkdir()
    out = Path(r._render_sequence_job('room', 'o', 'c', room, tmp_path / 'o')['output_path'])
    a = _frames(out)
    assert len(a) == 72                                    # the slot is 2.4 s
    src = _frames(tmp_path / 'room' / 'src.mov')
    # output frame k shows source frame ≈ k × 1.25
    want = np.array([src[min(len(src) - 1, round(k * SP))].mean() for k in range(72)])
    got = a.mean((1, 2))
    assert np.abs(got - want).max() < 2.5, np.abs(got - want).max()
    loud = _loud(out)                                       # 40 ms steps
    t = np.arange(len(loud)) * 0.04
    assert (loud[(t > 0.1) & (t < 1.5)] > 0.2).all()
    assert (loud[(t > 1.65) & (t < 1.88)] < 0.05).all()     # source 2.0-2.4 silent → timeline 1.6-1.92
    assert (loud[(t > 1.98) & (t < 2.34)] > 0.2).all()     # the last words are still heard
