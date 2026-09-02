"""ミキサー車のドラムを「つるん」とした白に塗り替える。

元画像のオレンジ／赤の帯だけを対象に、帯のまわりにある実物の白いドラム面の陰影を
2次元のプッシュプル補間（多重解像度の重み付き平均）で流し込む。行ごとの補間と違い
はしごや漏斗が横切っていても筋が出ず、単純な減色と違い帯の中に縞の凹凸が残らない。
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

BACKUP = Path("D:/dan-workspace/backup_mixer")
OUT_DIR = Path("D:/dan-workspace")
TARGETS = {
    # 名前: (元画像, 出力先, ドラムの範囲 x0,y0,x1,y1, 帯の最小面積)
    # 範囲を切るのは、ウインカーやテールランプの橙色まで白くしないため。
    "carousel": (
        BACKUP / "mixer_v2_orig.png",
        Path("D:/done/frontend/public/kikkawa/v2/vehicles/mixer.png"),
        (240, 330, 760, 800),
        100,
    ),
    "services": (
        BACKUP / "mixer_side_orig.png",
        Path("D:/done/frontend/public/kikkawa/vehicles/mixer.png"),
        (555, 295, 800, 615),
        500,
    ),
}


def warm_mask(bgr: np.ndarray, roi: tuple[int, int, int, int], min_area: int) -> np.ndarray:
    """ドラム範囲の中にあるオレンジ／赤の帯だけを抜く。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    m = ((s > 55) & (v > 50) & ((h < 25) | (h > 165))).astype(np.uint8)
    x0, y0, x1, y1 = roi
    box = np.zeros_like(m)
    box[y0:y1, x0:x1] = 1
    m &= box
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros_like(m)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            keep[labels == i] = 1
    # 帯の縁は影で色が薄くなる。薄い橙が地続きに続く範囲だけを追加で取り込む
    # （離れた場所にある淡い橙の部品＝銘板やランプは巻き込まない）。
    faint = ((s > 20) & (v > 25) & ((h < 28) | (h > 162))).astype(np.uint8) & box
    kernel = np.ones((3, 3), np.uint8)
    for _ in range(8):
        grown = cv2.dilate(keep, kernel) & faint
        if np.array_equal(grown, keep):
            break
        keep = grown
    # 縁のアンチエイリアスまで含めるよう太らせる
    return cv2.dilate(keep, np.ones((9, 9), np.uint8), iterations=1) & box


def background_mask(bgr: np.ndarray) -> np.ndarray:
    """写真の背景（なめらかな明るいグラデーション）を四隅から塗りつぶして特定する。"""
    h, w = bgr.shape[:2]
    flood = bgr.copy()
    ff = np.zeros((h + 2, w + 2), np.uint8)
    for seed in ((2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3)):
        cv2.floodFill(
            flood,
            ff,
            seed,
            (0, 0, 0),
            (6, 6, 6),
            (6, 6, 6),
            cv2.FLOODFILL_FIXED_RANGE | 4,
        )
    return ff[1:-1, 1:-1]


def pushpull_fill(bgr: np.ndarray, known: np.ndarray, levels: int = 8) -> np.ndarray:
    """既知画素だけを重みにした多重解像度の補間で、未知領域を滑らかに埋める。"""
    img = bgr.astype(np.float32)
    w = known.astype(np.float32)
    pyr_img = [img * w[:, :, None]]
    pyr_w = [w]
    for _ in range(levels):
        pyr_img.append(cv2.pyrDown(pyr_img[-1]))
        pyr_w.append(cv2.pyrDown(pyr_w[-1]))
    # 粗い層から順に、重みの薄いところへ上位の値を流し込む
    up_img = pyr_img[-1]
    up_w = pyr_w[-1]
    for i in range(levels - 1, -1, -1):
        size = (pyr_w[i].shape[1], pyr_w[i].shape[0])
        coarse_img = cv2.resize(up_img, size, interpolation=cv2.INTER_LINEAR)
        coarse_w = cv2.resize(up_w, size, interpolation=cv2.INTER_LINEAR)
        alpha = np.clip(pyr_w[i], 0, 1)
        up_img = pyr_img[i] + coarse_img * (1 - alpha)[:, :, None]
        up_w = pyr_w[i] + coarse_w * (1 - alpha)
    return up_img / np.maximum(up_w, 1e-6)[:, :, None]


def process(name: str) -> None:
    src_path, dst_path, roi, min_area = TARGETS[name]
    orig = cv2.imread(str(src_path), cv2.IMREAD_UNCHANGED)
    if orig is None:
        raise SystemExit(f"読めません: {src_path}")
    has_alpha = orig.shape[2] == 4
    bgr = orig[:, :, :3]
    alpha = orig[:, :, 3] if has_alpha else None

    band = warm_mask(bgr, roi, min_area)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    light = (hsv[:, :, 2] >= 120) & (hsv[:, :, 1] <= 60)

    if has_alpha:
        inside = alpha > 200
        # 輪郭の半透明画素にも塗りを届かせる（橙のふちが残るのを防ぐ）
        paintable = alpha > 8
    else:
        inside = background_mask(bgr) == 0
        paintable = inside

    # 陰影を写し取る元は「帯の近くにある、車体の白い面」だけに限る
    near = cv2.dilate(band, np.ones((41, 41), np.uint8), iterations=4).astype(bool)
    source = near & inside & light & (band == 0)

    filled = pushpull_fill(bgr, source.astype(np.uint8))
    target = band.astype(bool) & paintable
    # 継ぎ目が段差にならないよう、境界だけ数画素かけて溶かす
    feather = cv2.GaussianBlur(target.astype(np.float32), (0, 0), 4.0)[:, :, None]
    feather = np.clip(feather * 1.25, 0, 1)
    out = bgr.astype(np.float32) * (1 - feather) + filled * feather
    result = np.clip(out, 0, 255).astype(np.uint8)

    if has_alpha:
        written = np.dstack([result, alpha])
        preview = (result.astype(np.float32) * (alpha[:, :, None] / 255.0) + 255 * (1 - alpha[:, :, None] / 255.0)).astype(np.uint8)
    else:
        written = result
        preview = result
    cv2.imwrite(str(dst_path), written)
    cv2.imwrite(str(OUT_DIR / f"tmp_check_{name}.png"), preview)
    cv2.imwrite(str(OUT_DIR / f"tmp_mask_{name}.png"), np.dstack([band * 255, source.astype(np.uint8) * 255, inside.astype(np.uint8) * 255]))
    print(f"{name}: band={int(band.sum())}px source={int(source.sum())}px -> {dst_path}")


if __name__ == "__main__":
    for key in sys.argv[1:] or list(TARGETS):
        process(key)
