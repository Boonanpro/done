"""A moving region whose box changes size (faces tracked in スヤさん2本目, 2026-11-18): its mask
came from an endless color source, so a one-frame picture never finished, and the fps filter
dropped the only frame so the mosaic was missing. The pass must end and the box must be drawn."""

import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from app.api.production_asset_routes import _blur_chain_kf_sized, _focus_chain

W, H, FPS = 320, 180, 30
CAPTION = Path(tempfile.gettempdir()) / "dan-test-region-mask-caption.png"


def _run(graph: str, out: str, tmp: Path, frames: int) -> np.ndarray:
    fg = tmp / "g.txt"
    fg.write_text(graph, encoding="utf-8")
    png = tmp / "f_%03d.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-/filter_complex", str(fg), "-map", f"[{out}]",
                    "-frames:v", str(frames), str(png)], check=True, timeout=30)
    return np.stack([np.asarray(Image.open(tmp / f"f_{i + 1:03d}.png").convert("RGB"), dtype=int)
                     for i in range(frames)])


def _base(n: int) -> str:
    # the export's base: grid-stamped picture with a still caption (a PNG read by movie=) laid
    # over it — what the one-frame window of render_frame looks like; behind that overlay the
    # fps filter used to drop the only frame
    if not CAPTION.exists():
        Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(CAPTION)
    return (f"testsrc2=s={W}x{H}:r={FPS}:d={n / FPS:.5f},settb=1/{FPS},setpts=N[vcat];"
            f"movie=filename='{CAPTION}',format=rgba[cap];"
            f"[vcat][cap]overlay=0:0:enable='lt(t\\,0.5)'[vin]")


def _plain(tmp: Path, n: int) -> np.ndarray:
    return _run(_base(n) + ";[vin]null[o]", "o", tmp, n)


def _changed(a: np.ndarray, b: np.ndarray, box: tuple[int, int, int, int]) -> float:
    x0, y0, x1, y1 = box
    return float(np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]).mean())


def test_one_frame_window_finishes_and_draws_the_box(tmp_path):
    # the window starts in the middle of the effect: it is cut to [0, 1 frame)
    kf = [(0.0, 0.1, 0.1, 0.3, 0.4), (0.2, 0.2, 0.15, 0.2, 0.3)]
    filt, out = _blur_chain_kf_sized("vin", 1, kf, W, H, 0.0, 1 / FPS, "mosaic", FPS)
    got = _run(_base(1) + ";" + filt, out, tmp_path, 1)[0]
    (tmp_path / "p").mkdir()
    ref = _plain(tmp_path / "p", 1)[0]
    assert _changed(got, ref, (32, 18, 128, 90)) > 3  # inside the first key's box
    assert _changed(got, ref, (200, 120, 320, 180)) == 0  # far outside it


def test_effect_inside_a_longer_window_follows_its_keys(tmp_path):
    # effect 0.5–1.0 s of a 2 s window; keys are window times, the box moves right
    kf = [(0.5, 0.0, 0.0, 0.25, 0.3), (1.0, 0.6, 0.0, 0.3, 0.4)]
    filt, out = _blur_chain_kf_sized("vin", 1, kf, W, H, 0.5, 1.0, "mosaic", FPS)
    got = _run(_base(60) + ";" + filt, out, tmp_path, 60)
    (tmp_path / "p").mkdir()
    ref = _plain(tmp_path / "p", 60)
    assert _changed(got[10], ref[10], (0, 0, W, H)) == 0  # before the effect
    assert _changed(got[15], ref[15], (0, 0, 80, 54)) > 3  # at its start: the first key's box
    assert _changed(got[15], ref[15], (200, 0, 320, 54)) == 0
    assert _changed(got[29], ref[29], (200, 0, 280, 54)) > 3  # near its end: moved right
    assert _changed(got[40], ref[40], (0, 0, W, H)) == 0  # after it


def test_spotlight_finishes_on_one_frame(tmp_path):
    filt, out = _focus_chain("vin", 1, 40, 30, 80, 60, W, H, 0.0, 1 / FPS, "spotlight", FPS, None, 1.0)
    got = _run(_base(1) + ";" + filt, out, tmp_path, 1)[0]
    (tmp_path / "p").mkdir()
    ref = _plain(tmp_path / "p", 1)[0]
    assert _changed(got, ref, (240, 140, 320, 180)) > 3  # outside the box is dimmed
