"""吉川特装 v2 のクレーン車画像のブーム(青)を赤に塗り替える。

画像生成でやり直すと背景(黒グラデ)・構図・光が変わってしまい、他の10枚と揃わない。
そこで元画像の「青い塗装の画素だけ」を色相変換する。背景・車体・光は1pxも触らない。

青の塗装: H≈213deg, S≈0.59-0.63  ← これだけを拾う
窓ガラス: H=195, S=0.07 / 背景: S<=0.05  ← 彩度で確実に除外

使い方:
  python scripts/kittoku_recolor_crane.py            # 生成してプレビュー出力
  python scripts/kittoku_recolor_crane.py --apply    # 本番画像を差し替え
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend/public/kikkawa/v2/vehicles/crane.png"
PREVIEW = Path("C:/Users/Owner/AppData/Local/Temp/crane_red_recolor.png")

# 青い塗装の抽出条件
#
# 注意: 背景の黒グラデはクレーンと「同じ色相(H≈215)」で、しかも彩度が0.40まで上がる
# (ブームの青い発光が背景に滲んでいるため)。だから色相では分離できない。
# 分離できるのは彩度: 塗装 0.58-0.63 / 背景 <=0.40 の間に隙間がある。そこで切る。
HUE_CORE = (195.0, 235.0)   # 塗装の色相帯
SAT_CORE = 0.50             # 塗装と判定する彩度(背景の最大0.40より上に取る)
HUE_SOFT = (185.0, 245.0)   # 縁のアンチエイリアス用に少し広げる
SAT_SOFT_LO = 0.33          # ここから
SAT_SOFT_HI = 0.48          # ここまでで 0->1 に立ち上げる(帯を狭くして背景を巻き込まない)
MIN_BLOB = 400              # これ未満の塊は背景ノイズとして捨てる
DILATE = 5                  # クレーン領域の膨張(縁だけ拾う。広げると背景が入る)

TARGET_HUE = 2.0            # 赤
SAT_GAIN = 1.22             # 消防車のような鮮やかな赤に


def rgb_to_hsv(a: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
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


def hsv_to_rgb(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    c = v * s
    hp = (h % 360.0) / 60.0
    x = c * (1 - np.abs((hp % 2) - 1))
    z = np.zeros_like(c)
    seg = hp.astype(int) % 6
    table = [(c, x, z), (x, c, z), (z, c, x), (z, x, c), (x, z, c), (c, z, x)]
    r = np.zeros_like(c); g = np.zeros_like(c); b = np.zeros_like(c)
    for k, (rr, gg, bb) in enumerate(table):
        i = seg == k
        r[i], g[i], b[i] = rr[i], gg[i], bb[i]
    m = v - c
    return np.stack([r + m, g + m, b + m], axis=-1)


def build_mask(h: np.ndarray, s: np.ndarray) -> np.ndarray:
    """クレーンの青い塗装だけの soft mask (0..1) を返す。"""
    core = (h >= HUE_CORE[0]) & (h <= HUE_CORE[1]) & (s >= SAT_CORE)

    # 背景の点ノイズを除去: 大きな塊だけをクレーンとみなす
    lab, n = ndimage.label(core)
    keep = np.zeros_like(core)
    for idx in range(1, n + 1):
        blob = lab == idx
        if blob.sum() >= MIN_BLOB:
            keep |= blob

    # クレーン周辺だけに処理を限定(離れた場所の青は触らない)
    zone = ndimage.binary_dilation(keep, iterations=DILATE)

    # 縁のアンチエイリアスを拾うための soft alpha
    soft = (h >= HUE_SOFT[0]) & (h <= HUE_SOFT[1])
    alpha = np.clip((s - SAT_SOFT_LO) / (SAT_SOFT_HI - SAT_SOFT_LO), 0.0, 1.0)
    alpha = np.where(soft & zone, alpha, 0.0)
    alpha = np.maximum(alpha, np.where(keep, 1.0, 0.0))
    return alpha


def main() -> int:
    apply = "--apply" in sys.argv
    im = Image.open(SRC).convert("RGB")
    a = np.asarray(im).astype(np.float32) / 255.0

    h, s, v = rgb_to_hsv(a)
    alpha = build_mask(h, s)

    # 赤へ: 色相を差し替え、明暗(V)はそのまま維持 -> 陰影・ハイライトが保たれる
    h_new = np.full_like(h, TARGET_HUE)
    s_new = np.clip(s * SAT_GAIN, 0.0, 1.0)
    recolored = hsv_to_rgb(h_new, s_new, v)

    out = a * (1 - alpha[..., None]) + recolored * alpha[..., None]
    img = Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8))

    covered = int((alpha > 0.5).sum())
    print(f"塗り替えた画素: {covered} ({100*covered/alpha.size:.2f}%)")

    if apply:
        img.save(SRC)
        print(f"適用: {SRC}")
    else:
        img.save(PREVIEW)
        print(f"プレビュー: {PREVIEW}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
