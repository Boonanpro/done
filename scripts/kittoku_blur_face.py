"""採用CTA写真(careers-cta-v2.jpg)の右端の人物の顔にガウスぼかしをかける。

四角いモザイクではなく、顔の輪郭に沿った楕円の範囲にガウスぼかしを当て、
マスク自体もぼかして境界を溶かす。加工範囲は顔だけで、他は元のまま。

使い方:
  python scripts/kittoku_blur_face.py            # プレビュー出力
  python scripts/kittoku_blur_face.py --apply    # 本番画像を差し替え
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend/public/kikkawa/careers-cta-v2.jpg"
PREVIEW = Path("C:/Users/Owner/AppData/Local/Temp/careers_face_blur.png")

# 右端の人物の顔(額〜あご、左頬〜耳)を囲む楕円。画像は 1616x1080。
FACE_CX, FACE_CY = 1292, 312
FACE_RX, FACE_RY = 74, 92

BLUR_RADIUS = 24     # 顔を判別不能にする強さ
FEATHER = 16         # マスク境界のぼかし(大きいほど自然に溶ける)
JPEG_QUALITY = 92


def main() -> int:
    apply = "--apply" in sys.argv
    im = Image.open(SRC).convert("RGB")
    W, H = im.size

    # 1. 全体をガウスぼかししたものを用意
    blurred = im.filter(ImageFilter.GaussianBlur(radius=BLUR_RADIUS))

    # 2. 顔の楕円マスクを作り、マスク自体をぼかして境界を柔らかくする
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse(
        [FACE_CX - FACE_RX, FACE_CY - FACE_RY, FACE_CX + FACE_RX, FACE_CY + FACE_RY],
        fill=255,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(radius=FEATHER))

    # 3. 合成: 顔だけ差し替わり、周囲へなめらかに減衰する
    out = Image.composite(blurred, im, mask)

    covered = int((np.asarray(mask) > 127).sum())
    print(f"ぼかした範囲: 楕円 中心({FACE_CX},{FACE_CY}) 半径({FACE_RX},{FACE_RY}) = {covered}px")

    if apply:
        out.save(SRC, quality=JPEG_QUALITY, subsampling=0)
        print(f"適用: {SRC}")
    else:
        out.save(PREVIEW)
        print(f"プレビュー: {PREVIEW}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
