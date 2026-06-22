"""成果物のアイコン（favicon）を任意の画像に差し替える。

ダンがチャットで「○○のアイコンをこの画像に変えて」と頼まれた時に使う。
渡した画像を logo として保存し、icon-192 / icon-512 / apple-touch を作り直す。
metadata は固定パスを参照しているので、PNG を差し替えるだけで
ブラウザタブ・検索結果に反映される（配線が未済なら自動で配線もする）。

使い方:
  python scripts/set_artifact_icon.py --slug kittoku --image path/to/logo.png

差し替え後の公開反映:
  git add frontend/public/artifacts/<slug>/  (PNG は scope=ignored なので自由)
  git add frontend/src/app/artifacts/<slug>/layout.tsx  (初回配線時のみ)
  commit & push → Vercel 自動デプロイ
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.artifact_public_assets import set_artifact_icon_from_image  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="成果物アイコンを画像から差し替える")
    parser.add_argument("--slug", required=True, help="成果物 slug (例: kittoku)")
    parser.add_argument("--image", required=True, help="アイコンにする画像ファイルのパス")
    parser.add_argument(
        "--no-wire",
        action="store_true",
        help="layout.tsx への配線をスキップ（PNG 差し替えのみ）",
    )
    args = parser.parse_args()

    image = Path(args.image)
    if not image.exists():
        print(f"画像が見つかりません: {image}", file=sys.stderr)
        return 1

    created = set_artifact_icon_from_image(args.slug, image)
    if not created:
        print("アイコン生成に失敗しました（Pillow 未導入 / 画像が壊れている可能性）", file=sys.stderr)
        return 1

    print(f"アイコン更新: {args.slug}")
    for key, rel in created.items():
        print(f"  {key:>5}: {rel}")

    if not args.no_wire:
        from wire_artifact_icons import wire_slug  # noqa: E402

        status = wire_slug(args.slug)
        print(f"配線: {status}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
