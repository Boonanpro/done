# -*- coding: utf-8 -*-
"""画像ファーストLP: タイル画像から操作箇所を検出して具現化ページの雛形を生成する。

GPT Image 2 等で生成した縦長LPタイル画像（ボタン・入力欄が描き込まれている）から、
実HTML化すべき領域を色検出で特定し、座標JSONと page.tsx 雛形を出力する。

使い方:
  python scripts/lp_image_materialize.py --images t1.png t2.png t3.png \
      --slug my-lp --out-json coords.json [--out-page page.tsx]

検出ルール:
  - ボタン: 彩度の高い大きな角丸塊（幅がタイル幅の25%以上、高さ40px以上）
    hue 90-180° → role "line"（LINE緑）, それ以外 → "cta"
  - 入力欄: ほぼ白の横長塊（幅45%以上・高さ40〜160px）で、
    下方200px以内にボタンがあるもの（白カード誤検出を除くための条件）
  - 入力欄の直下にあるボタンは role "submit" に昇格
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


def _boxes(mask: np.ndarray, min_w: int, min_h: int) -> list[tuple[int, int, int, int]]:
    lab, _ = ndimage.label(mask)
    out = []
    for sl in ndimage.find_objects(lab):
        if sl is None:
            continue
        ys, xs = sl
        w, h = xs.stop - xs.start, ys.stop - ys.start
        if w >= min_w and h >= min_h:
            out.append((xs.start, ys.start, xs.stop, ys.stop))
    return sorted(out, key=lambda b: b[1])


def detect_tile(path: Path) -> dict:
    im = Image.open(path).convert("RGB")
    W, H = im.size
    arr = np.array(im).astype(np.int32)
    hsv = np.array(im.convert("HSV")).astype(np.int32)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    # ボタン: 彩度高・明度中以上の大きな塊。
    # 写真・イラストの誤検出を除くため「ベタ塗り（RGB分散が小さい）」を要求する。
    sat_mask = (sat > 115) & (val > 110)
    buttons = []
    for x0, y0, x1, y1 in _boxes(sat_mask, min_w=int(W * 0.25), min_h=40):
        region_mask = sat_mask[y0:y1, x0:x1]
        fill = float(region_mask.mean())
        pixels = arr[y0:y1, x0:x1][region_mask]
        color_std = float(pixels.std(axis=0).mean())
        # ボタンは角丸長方形なのでbboxをほぼ埋める(実測89-94%)。
        # 水彩ベタ塗り(斜めのラグ等)は形が不定形で埋まらない(実測50%)
        if fill < 0.80 or color_std > 28:
            continue  # 写真・水彩イラスト等
        if (x1 - x0) < (y1 - y0) * 2.5:
            continue  # ボタンは横長。図表のベタ塗り(正方形に近い)を除外
        # ボタンは背景に浮いている＝周囲12pxリングは彩度が低いはず。
        # 大きなカードの一部（比較カードの見出し帯等）を除外する
        ry0, ry1 = max(0, y0 - 12), min(H, y1 + 12)
        rx0, rx1 = max(0, x0 - 12), min(W, x1 + 12)
        ring = sat_mask[ry0:ry1, rx0:rx1].sum() - sat_mask[y0:y1, x0:x1].sum()
        ring_area = (ry1 - ry0) * (rx1 - rx0) - (y1 - y0) * (x1 - x0)
        if ring_area > 0 and ring / ring_area > 0.30:
            continue
        region_hue = hue[y0:y1, x0:x1][region_mask]
        h_med = float(np.median(region_hue)) * 360 / 255  # PIL HSVは0-255
        role = "line" if 90 <= h_med <= 180 else "cta"
        buttons.append({"bbox": [int(x0), int(y0), int(x1), int(y1)], "hue": round(h_med), "role": role})

    # 入力欄候補: ほぼ白の横長塊
    R, G, B = arr[..., 0], arr[..., 1], arr[..., 2]
    white_mask = (R > 243) & (G > 243) & (B > 238)
    inputs = []
    for x0, y0, x1, y1 in _boxes(white_mask, min_w=int(W * 0.45), min_h=40):
        if (y1 - y0) > 240:
            continue  # 白カードや余白は除外（入力欄の高さ上限）
        # 文字入りの白カード(FAQ等)を除外: 入力欄の中身はプレースホルダのみで
        # 暗い画素がほとんど無い
        interior = arr[y0:y1, x0:x1]
        dark_ratio = float((interior.sum(axis=2) < 330).mean())
        if dark_ratio > 0.04:
            continue
        near_button = any(
            0 < b["bbox"][1] - y1 < 200 and b["bbox"][0] < x1 and b["bbox"][2] > x0
            for b in buttons
        )
        if near_button:
            inputs.append({"bbox": [int(x0), int(y0), int(x1), int(y1)]})

    # 入力欄の直下のボタンは submit
    for inp in inputs:
        below = [
            b for b in buttons
            if 0 < b["bbox"][1] - inp["bbox"][3] < 400
            and b["bbox"][0] < inp["bbox"][2] and b["bbox"][2] > inp["bbox"][0]
        ]
        for b in sorted(below, key=lambda b: b["bbox"][1]):
            if b["role"] == "cta":
                b["role"] = "submit"
                break

    return {"file": path.name, "width": W, "height": H, "buttons": buttons, "inputs": inputs}


PAGE_TEMPLATE = '''"use client";

/**
 * 画像ファーストLP（自動生成雛形: scripts/lp_image_materialize.py）
 * タイル画像を縦に繋ぎ、検出された操作箇所に実HTMLを重ねる。
 * TODO: 送信先API・ボタンの遷移先を案件に合わせて調整すること。
 */

import {{ useRef, useState }} from "react";

const TILES = {tiles_json};

function pct(v: number, base: number) {{
  return `${{(v / base) * 100}}%`;
}}

export default function ImageFirstLp() {{
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "done" | "error" | "invalid">("idle");
  const inputRef = useRef<HTMLInputElement>(null);

  const scrollToForm = () => {{
    inputRef.current?.scrollIntoView({{ behavior: "smooth", block: "center" }});
    setTimeout(() => inputRef.current?.focus(), 500);
  }};

  const submit = async () => {{
    const value = email.trim();
    if (!/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(value)) {{
      setStatus("invalid");
      inputRef.current?.focus();
      return;
    }}
    setStatus("sending");
    try {{
      const res = await fetch("/api/v1/inquiries", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          scope: "{slug}-waitlist", // TODO: 案件のscopeに変更
          name: "LP登録",
          email: value,
          message: `登録: ${{value}}`,
          source_url: window.location.href,
        }}),
      }});
      if (!res.ok) throw new Error(await res.text());
      setStatus("done");
    }} catch {{
      setStatus("error");
    }}
  }};

  return (
    <main className="min-h-screen" style={{{{ background: "{bg}" }}}}>
      <div className="mx-auto w-full max-w-[560px]">
        {{TILES.map((tile, ti) => (
          <div key={{ti}} className="relative">
            {{/* eslint-disable-next-line @next/next/no-img-element */}}
            <img src={{`{public_prefix}/${{tile.file}}`}} alt={{tile.alt}} className="block w-full" draggable={{false}} />
            {{tile.inputs.map((box, i) => (
              <input
                key={{`in-${{i}}`}}
                ref={{inputRef}}
                type="email"
                value={{email}}
                onChange={{(e) => {{ setEmail(e.target.value); if (status !== "idle") setStatus("idle"); }}}}
                placeholder="メールアドレスを入力してください"
                style={{{{
                  position: "absolute",
                  left: pct(box.bbox[0], tile.width),
                  top: pct(box.bbox[1], tile.height),
                  width: pct(box.bbox[2] - box.bbox[0], tile.width),
                  height: pct(box.bbox[3] - box.bbox[1], tile.height),
                  background: "#fff",
                  border: status === "invalid" ? "2px solid #d43c2a" : "1px solid #ddd",
                  borderRadius: 12,
                  padding: "0 1em",
                  fontSize: "clamp(11px, 3.3vw, 15px)",
                  outline: "none",
                }}}}
              />
            ))}}
            {{tile.buttons.map((box, i) => (
              <button
                key={{`bt-${{i}}`}}
                type="button"
                aria-label={{box.role}}
                style={{{{
                  position: "absolute",
                  left: pct(box.bbox[0], tile.width),
                  top: pct(box.bbox[1], tile.height),
                  width: pct(box.bbox[2] - box.bbox[0], tile.width),
                  height: pct(box.bbox[3] - box.bbox[1], tile.height),
                  background: "transparent",
                  border: "none",
                  borderRadius: 12,
                  cursor: "pointer",
                }}}}
                className="transition hover:bg-white/15 active:bg-black/10"
                onClick={{box.role === "submit" ? submit : scrollToForm}} // TODO: lineボタンはLINE友だち追加URLへ
              />
            ))}}
          </div>
        ))}}
      </div>
      {{status === "done" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6">
          <div className="max-w-sm rounded-2xl bg-white p-8 text-center shadow-xl">
            <p className="text-lg font-bold">登録を受け付けました</p>
            <button type="button" className="mt-6 rounded-full bg-neutral-800 px-8 py-2.5 text-sm font-bold text-white" onClick={{() => {{ setStatus("idle"); setEmail(""); }}}}>閉じる</button>
          </div>
        </div>
      )}}
    </main>
  );
}}
'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--images", nargs="+", required=True, help="タイル画像（上から順）")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-page", help="page.tsx 雛形の出力先（省略可）")
    ap.add_argument("--public-prefix", default=None, help="imgのsrcプレフィックス (default: /scratch/<slug>)")
    args = ap.parse_args()

    tiles = []
    for p in args.images:
        info = detect_tile(Path(p))
        info["alt"] = f"{args.slug} LP"
        tiles.append(info)
        print(f"{info['file']}: buttons={[(b['role'], b['bbox']) for b in info['buttons']]} "
              f"inputs={[i['bbox'] for i in info['inputs']]}")

    Path(args.out_json).write_text(json.dumps(tiles, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out_json}")

    if args.out_page:
        # 背景色: 1枚目の四隅の平均
        im = np.array(Image.open(args.images[0]).convert("RGB"))
        corners = np.concatenate([im[:40, :40].reshape(-1, 3), im[:40, -40:].reshape(-1, 3)])
        bg = "#{:02x}{:02x}{:02x}".format(*corners.mean(axis=0).astype(int))
        page = PAGE_TEMPLATE.format(
            tiles_json=json.dumps(tiles, ensure_ascii=False, indent=2),
            slug=args.slug,
            bg=bg,
            public_prefix=args.public_prefix or f"/scratch/{args.slug}",
        )
        Path(args.out_page).write_text(page, encoding="utf-8")
        print(f"wrote {args.out_page}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
