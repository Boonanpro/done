# -*- coding: utf-8 -*-
"""画像ファーストLP: 部分修正の合成ツール。

GPT Image 2 の参照編集は全体を微妙に描き直す（写真の細部が変わる）ため、
「編集後の画像から変更したい領域だけを切り出して元画像に貼る」ことで
領域外の完全不変を保証する。2026-08-03 の実測で領域外変化 0.0000% を確認済み。

使い方:
  # 領域を明示（推奨。編集指示を出した本人が場所を知っているため）
  python scripts/lp_image_patch.py --original t1.png --edited t1_new.png \
      --region 43,1608,1471,1834 --out t1_patched.png

  # 自動検出（変更領域の見当がつかない場合。結果のbboxを必ず目視確認すること）
  python scripts/lp_image_patch.py --original t1.png --edited t1_new.png \
      --auto --out t1_patched.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


def auto_region(a: np.ndarray, b: np.ndarray) -> tuple[int, int, int, int]:
    """意図した変更領域を差分から推定する。

    全体ドリフト（輪郭のにじみ・写真の描き直し）は「弱く散らばる」のに対し、
    意図した変更（文字の差し替え等）は「強く密集する」。
    強い差分のみを取り、密度スコア最大の連結成分を選ぶ。
    """
    diff = np.abs(a.astype(np.int32) - b.astype(np.int32)).sum(axis=2)
    # 350 = 白⇔オレンジ級の色置換だけが残るしきい値。再描画による文字輪郭の
    # にじみ(同じ文字の描き直し)はこれを超えない。実測でチューニング済み。
    strong = diff > 350
    strong = ndimage.binary_dilation(strong, iterations=20)
    lab, n = ndimage.label(strong)
    if n == 0:
        raise SystemExit("差分が検出できません（画像が同一か、変更が弱すぎます）")
    best, best_score = None, -1.0
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        ys, xs = sl
        area = (ys.stop - ys.start) * (xs.stop - xs.start)
        density = float((lab[sl] == i).mean())
        score = area * density * density  # 密度を強く効かせる
        if score > best_score:
            best_score, best = score, (xs.start, ys.start, xs.stop, ys.stop)
    return best  # type: ignore[return-value]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--original", required=True)
    ap.add_argument("--edited", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--region", help="x0,y0,x1,y1（編集後画像から貼る領域）")
    ap.add_argument("--auto", action="store_true", help="変更領域を差分から自動推定")
    ap.add_argument("--pad", type=int, default=8, help="領域の外周に足す余白px")
    args = ap.parse_args()

    orig = Image.open(args.original).convert("RGB")
    edit = Image.open(args.edited).convert("RGB")
    if edit.size != orig.size:
        print(f"note: サイズ不一致 {edit.size} → {orig.size} にリサイズ")
        edit = edit.resize(orig.size)
    a, b = np.array(orig), np.array(edit)

    if args.region:
        x0, y0, x1, y1 = (int(v) for v in args.region.split(","))
    elif args.auto:
        x0, y0, x1, y1 = auto_region(a, b)
    else:
        raise SystemExit("--region か --auto を指定してください")

    p = args.pad
    x0, y0 = max(0, x0 - p), max(0, y0 - p)
    x1, y1 = min(orig.width, x1 + p), min(orig.height, y1 + p)

    merged = orig.copy()
    merged.paste(edit.crop((x0, y0, x1, y1)), (x0, y0))
    merged.save(args.out)

    m = np.array(merged)
    changed = (np.abs(a.astype(np.int32) - m.astype(np.int32)).sum(axis=2) > 30)
    outside = changed.copy()
    outside[y0:y1, x0:x1] = False
    print(f"region: {x0},{y0},{x1},{y1}")
    print(f"changed inside region: {changed[y0:y1, x0:x1].mean() * 100:.2f}%")
    print(f"changed OUTSIDE region: {outside.mean() * 100:.4f}%  (0.0000%であること)")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
