"""ヒーロー5シーン目の塵芥車のピンク塗装だけを青に置き換える（動画・全フレーム）。

AI動画モデル(Gemini)は全フレームを描き直すため、細い排気管が
フレームごとに変わってちらつく。ここでは元動画の「ピンクの画素だけ」を
色相変換する。排気管・背景・ナンバー等は1pxも触らないので、
構造上ちらつきようがない。元の1080p/30fpsをそのまま維持する。

ピンク: H 295-350 / 既存の青: H 205-245 とはっきり分離できる（実測済み）。

使い方:
  python scripts/kittoku_recolor_car_video.py <入力mp4> <出力mp4>
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

FFMPEG = "C:/Users/Owner/ffmpeg/bin/ffmpeg.exe"
FFPROBE = "C:/Users/Owner/ffmpeg/bin/ffprobe.exe"

# ピンク塗装の抽出条件（実測: ピンク H≈320 S≈0.42 / 既存の青 H≈222）
# ピンクは濃い部分(S~0.42)だけでなく、屋根/ボンネットのパステル調(S~0.1)まである。
# 薄いピンクを塗り残すと青と混ざって紫に見えるので、彩度の下限を下げて広く拾う。
# 白(S<0.04)は拾わないので窓/ナンバー/ヘッドライトは無傷。
HUE_LO, HUE_HI = 285.0, 355.0
SAT_CORE = 0.09          # これ以上はピンク塗装として完全に塗り替える
SAT_SOFT_LO = 0.045      # 縁のアンチエイリアス（白との境界）
SAT_SOFT_HI = 0.09

TARGET_HUE = 221.0       # 既存の下部ブルーに合わせる
SAT_GAIN = 1.55          # パステルの薄いピンクも下部ブルー並みの鮮やかな青にする


def rgb_to_hsv(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(2), a.min(2)
    d = mx - mn
    h = np.zeros_like(mx)
    m = d > 1e-6
    i = m & (mx == r); h[i] = ((g - b)[i] / d[i]) % 6
    i = m & (mx == g); h[i] = ((b - r)[i] / d[i]) + 2
    i = m & (mx == b); h[i] = ((r - g)[i] / d[i]) + 4
    h *= 60.0
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0)
    return h, s, mx


def hsv_to_rgb(h, s, v):
    c = v * s
    hp = (h % 360.0) / 60.0
    x = c * (1 - np.abs((hp % 2) - 1))
    z = np.zeros_like(c)
    seg = hp.astype(int) % 6
    tbl = [(c, x, z), (x, c, z), (z, c, x), (z, x, c), (x, z, c), (c, z, x)]
    r = np.zeros_like(c); g = np.zeros_like(c); b = np.zeros_like(c)
    for k, (rr, gg, bb) in enumerate(tbl):
        i = seg == k
        r[i], g[i], b[i] = rr[i], gg[i], bb[i]
    m = v - c
    return np.stack([r + m, g + m, b + m], axis=-1)


def recolor(rgb: np.ndarray) -> np.ndarray:
    a = rgb.astype(np.float32) / 255.0
    h, s, v = rgb_to_hsv(a)
    in_hue = (h >= HUE_LO) & (h <= HUE_HI)
    alpha = np.clip((s - SAT_SOFT_LO) / (SAT_SOFT_HI - SAT_SOFT_LO), 0.0, 1.0)
    alpha = np.where(in_hue, alpha, 0.0)
    h_new = np.full_like(h, TARGET_HUE)
    s_new = np.clip(s * SAT_GAIN, 0.0, 1.0)
    out = a * (1 - alpha[..., None]) + hsv_to_rgb(h_new, s_new, v) * alpha[..., None]
    return (np.clip(out, 0, 1) * 255).astype(np.uint8)


def main() -> int:
    src, dst = sys.argv[1], sys.argv[2]
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-of", "default=noprint_wrappers=1:nokey=1", src],
        capture_output=True, text=True).stdout.split()
    w, h = int(probe[0]), int(probe[1])
    fps = probe[2]

    # デコード: rawvideo を stdin から読む
    dec = subprocess.Popen(
        [FFMPEG, "-v", "error", "-i", src, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE)
    enc = subprocess.Popen(
        [FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{w}x{h}", "-r", fps, "-i", "-",
         "-c:v", "libx264", "-crf", "16", "-preset", "slow",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", dst],
        stdin=subprocess.PIPE)

    frame_bytes = w * h * 3
    n = 0
    while True:
        buf = dec.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        frame = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)
        enc.stdin.write(recolor(frame).tobytes())
        n += 1
    enc.stdin.close()
    dec.wait(); enc.wait()
    print(f"処理フレーム数: {n}  出力: {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
