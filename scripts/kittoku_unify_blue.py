"""塵芥車を「1色の青」に統一し、側面のモザイクを消す（試作: 1フレーム）。

- ピンク(H285-355) と 既存の青(H198-248) の両方を同じ青(H221)に寄せる。
  明暗(V)は残すので陰影は保たれ、1色に塗られたように見える。
- モザイク=黄緑(H40-160)のブロック。青い車体に囲まれた黄緑だけを対象にし、
  cv2.inpaint で周囲の青で塗りつぶす（背景の黄色は青に囲まれないので除外）。

使い方: python scripts/kittoku_unify_blue.py <in.jpg|frame> <out.png>
"""
from __future__ import annotations
import sys
import numpy as np
import cv2
from PIL import Image

TARGET_HUE = 221.0
SAT_TARGET = 0.62         # 1色に見せるため彩度も揃える


def rgb_to_hsv(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(2), a.min(2); d = mx - mn
    h = np.zeros_like(mx); m = d > 1e-6
    i = m & (mx == r); h[i] = ((g - b)[i] / d[i]) % 6
    i = m & (mx == g); h[i] = ((b - r)[i] / d[i]) + 2
    i = m & (mx == b); h[i] = ((r - g)[i] / d[i]) + 4
    h *= 60.0
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0)
    return h, s, mx


def hsv_to_rgb(h, s, v):
    c = v * s; hp = (h % 360.0) / 60.0
    x = c * (1 - np.abs((hp % 2) - 1)); z = np.zeros_like(c)
    seg = hp.astype(int) % 6
    tbl = [(c, x, z), (x, c, z), (z, c, x), (z, x, c), (x, z, c), (c, z, x)]
    r = np.zeros_like(c); g = np.zeros_like(c); b = np.zeros_like(c)
    for k, (rr, gg, bb) in enumerate(tbl):
        i = seg == k; r[i], g[i], b[i] = rr[i], gg[i], bb[i]
    m = v - c
    return np.stack([r + m, g + m, b + m], axis=-1)


def unify_blue(rgb: np.ndarray) -> np.ndarray:
    a = rgb.astype(np.float32) / 255.0
    h, s, v = rgb_to_hsv(a)
    # ピンク + 既存の青 の両方を車体色とみなす
    pink = (h >= 285) & (h <= 355) & (s >= 0.09)
    blue = (h >= 198) & (h <= 248) & (s >= 0.20)
    body = pink | blue
    alpha = np.clip((s - 0.04) / (0.09 - 0.04), 0.0, 1.0) * body
    h_new = np.full_like(h, TARGET_HUE)
    s_new = np.where(body, np.maximum(s, SAT_TARGET), s)
    out = a * (1 - alpha[..., None]) + hsv_to_rgb(h_new, s_new, v) * alpha[..., None]
    return (np.clip(out, 0, 1) * 255).astype(np.uint8), body


def remove_mosaic(rgb: np.ndarray, body: np.ndarray) -> np.ndarray:
    a = rgb.astype(np.float32) / 255.0
    h, s, v = rgb_to_hsv(a)
    # 黄緑(モザイクの色)
    ymask = ((h >= 38) & (h <= 170) & (s >= 0.30) & (v >= 0.35)).astype(np.uint8)
    # 車体(青)に囲まれているものだけ残す: bodyを膨張した内側にある黄緑
    body_d = cv2.dilate(body.astype(np.uint8), np.ones((41, 41), np.uint8))
    ymask = ymask & body_d
    # 近傍がある程度まとまっている塊だけ(点ノイズ除去)
    ymask = cv2.morphologyEx(ymask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ymask, 8)
    keep = np.zeros_like(ymask)
    for k in range(1, n):
        if stats[k, cv2.CC_STAT_AREA] >= 150:
            keep[lab == k] = 1
    keep = cv2.dilate(keep, np.ones((13, 13), np.uint8))
    if keep.sum() == 0:
        return rgb
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    inp = cv2.inpaint(bgr, keep, 6, cv2.INPAINT_TELEA)
    return cv2.cvtColor(inp, cv2.COLOR_BGR2RGB)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    rgb = np.asarray(Image.open(src).convert("RGB"))
    blued, body = unify_blue(rgb)
    final = remove_mosaic(blued, body)
    Image.fromarray(final).save(dst)
    print("out:", dst)


if __name__ == "__main__":
    main()
