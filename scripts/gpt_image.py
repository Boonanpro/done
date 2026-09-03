"""GPT Image 2 を OpenAI API 直で叩く画像生成CLI。

ダンの汎用画像生成（LP・デザイン・文字入り画像）はこれが正規経路。
Higgsfield は動画・Soul ID・Nano Banana 系専用（GPT Image 2 をここへ一本化した
2026-08-11 の決定。単価は同等だが、自由サイズとマスク編集が使える）。

プロンプトは必ず標準入力で渡す（higgsfield CLI で引数渡しがフラグを壊した教訓と同じ規律）:

    echo "プロンプト" | python scripts/gpt_image.py --out t1.png
    cat p.txt | python scripts/gpt_image.py --size 1520x2688 --quality low --out t1.png
    cat p.txt | python scripts/gpt_image.py --image comp_slice.png --out t1.png   # 参照つき
    cat p.txt | python scripts/gpt_image.py --image t1.png --mask m.png --out t1v2.png  # 領域修正

サイズ制約（API仕様）: 両辺16の倍数 / 最長辺3840px以下 / 縦横比3:1以内 /
総画素 655,360〜8,294,400。既定 1520x2688 はLPタイルの現行寸法。
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent  # D:/done（cwd に依存しない）

# 概算単価（2026-08 時点の公表レート。請求の正は OpenAI ダッシュボード）
_USD_PER_M = {"text_in": 5.0, "image_in": 8.0, "image_out": 30.0}


def _load_api_key() -> str:
    import os

    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
                break
    if not key:
        sys.exit("OPENAI_API_KEY が環境変数にも .env にもありません")
    return key


def _validate_size(size: str) -> str:
    try:
        w, h = (int(v) for v in size.lower().split("x"))
    except ValueError:
        sys.exit(f"--size は WxH 形式で指定: {size}")
    problems = []
    if w % 16 or h % 16:
        problems.append("両辺とも16の倍数が必要")
    if max(w, h) > 3840:
        problems.append("最長辺は3840px以下")
    if max(w, h) / min(w, h) > 3:
        problems.append("縦横比は3:1以内")
    if not 655_360 <= w * h <= 8_294_400:
        problems.append("総画素は655,360〜8,294,400")
    if problems:
        sys.exit(f"サイズ {size} はAPI制約違反: {' / '.join(problems)}")
    return f"{w}x{h}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="出力PNGパス")
    ap.add_argument("--size", default="1520x2688", help="WxH（既定=LPタイル寸法）")
    ap.add_argument("--quality", default="low", choices=["low", "medium", "high", "auto"])
    ap.add_argument("--image", action="append", default=[],
                    help="参照画像（複数可）。指定すると edits エンドポイントになる")
    ap.add_argument("--mask", help="修正領域マスクPNG（透明部分が編集対象。--image 必須）")
    ap.add_argument("--json", action="store_true", help="結果をJSONで標準出力へ")
    args = ap.parse_args()

    # Windows コンソールの cp932 に汚染されないよう、標準入力はバイトで読む
    prompt = sys.stdin.buffer.read().decode("utf-8", errors="replace").strip()
    if not prompt:
        sys.exit("プロンプトを標準入力で渡してください")
    if args.mask and not args.image:
        sys.exit("--mask には --image が必要です")

    headers = {"Authorization": f"Bearer {_load_api_key()}"}
    size = _validate_size(args.size)
    started = time.time()

    if args.image:
        files = [("image[]", (Path(p).name, Path(p).read_bytes(), "image/png"))
                 for p in args.image]
        if args.mask:
            files.append(("mask", (Path(args.mask).name, Path(args.mask).read_bytes(), "image/png")))
        r = requests.post(
            "https://api.openai.com/v1/images/edits",
            headers=headers,
            data={"model": "gpt-image-2", "prompt": prompt, "size": size,
                  "quality": args.quality},
            files=files,
            timeout=600,
        )
    else:
        r = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers=headers,
            json={"model": "gpt-image-2", "prompt": prompt, "size": size,
                  "quality": args.quality},
            timeout=600,
        )

    if r.status_code != 200:
        sys.exit(f"API error {r.status_code}: {r.text[:500]}")
    body = r.json()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(body["data"][0]["b64_json"]))

    usage = body.get("usage", {})
    detail = usage.get("input_tokens_details", {})
    cost = (
        detail.get("text_tokens", 0) / 1e6 * _USD_PER_M["text_in"]
        + detail.get("image_tokens", 0) / 1e6 * _USD_PER_M["image_in"]
        + usage.get("output_tokens", 0) / 1e6 * _USD_PER_M["image_out"]
    )
    result = {
        "out": str(out),
        "size": size,
        "quality": args.quality,
        "seconds": round(time.time() - started, 1),
        "usage": usage,
        "cost_usd_approx": round(cost, 4),
    }
    print(json.dumps(result, ensure_ascii=False) if args.json
          else f"saved {out} ({size}, {args.quality}, ~${cost:.3f})")


if __name__ == "__main__":
    main()
