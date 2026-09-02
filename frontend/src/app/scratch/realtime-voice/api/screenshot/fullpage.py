"""認証付きフルページスクリーンショット（音声エージェントの「確認の目」）。

look_at_page の裏側。getDisplayMedia（画面共有）と違い:
  - スクロール全域を1枚で撮る（ファーストビューだけで判断しない）
  - done_access_token クッキーを注入するので draft override も写る
  - 許可ダイアログ不要

usage: python fullpage.py --url http://localhost:3000/artifacts/test-edit \
         --out shot.jpg [--token JWT] [--width 1280]
"""
import argparse
import sys

from playwright.sync_api import sync_playwright


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--token", default="")
    ap.add_argument("--width", type=int, default=1280)
    # 特定要素だけを原寸で撮る（look_at_section）。全域の縮小画像では小さい文字の
    # コントラスト崩れが見えないため、細部確認はこちらを使う。
    ap.add_argument("--selector", default="")
    # 汎用の目モード: 全域を原寸で撮り、縦にタイル分割して各タイルを out の連番で保存。
    # 1枚の縮小画像では文字が読めず「汎用知能が自分で気付く」が成立しないための本命modo。
    ap.add_argument("--tiles", type=int, default=0, help="0=単発 / N>0=最大Nタイルに分割")
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": args.width, "height": 900})
        if args.token:
            context.add_cookies(
                [{"name": "done_access_token", "value": args.token, "url": "http://localhost:3000"}]
            )
        page = context.new_page()
        page.goto(args.url, wait_until="networkidle", timeout=25000)
        # InspectorRuntime の draft fetch → DOM 適用を待つ
        page.wait_for_timeout(1500)
        # スクロール出現アニメーション対策: アニメを強制的に最終状態へ。
        # スクロールで舐める方式は full_page 撮影では発火しないことがある（実測）ため、
        # CSSで opacity/transform/animation を無効化して「表示され切った姿」を撮る。
        page.add_style_tag(
            content="*{opacity:1 !important; transform:none !important; "
            "animation:none !important; transition:none !important;}"
        )
        page.wait_for_timeout(400)
        if args.selector:
            el = page.locator(args.selector).first
            el.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            el.screenshot(path=args.out, type="jpeg", quality=85)
        else:
            page.screenshot(path=args.out, full_page=True, type="jpeg", quality=80)
        browser.close()

    if args.tiles > 0 and not args.selector:
        _slice_tiles(args.out, args.tiles)
        return

    # WebRTC data channel の上限（約256KB、base64で1.33倍に膨らむ）に収まるよう圧縮する。
    # 実測: 無圧縮1280幅の縦長LPで475KB超→送信失敗。170KB(base64後216KB)でも
    # 送信直後にモデルが完全沈黙する事象があったため、目標をさらに安全側の 110KB に下げる。
    _shrink_to_fit(args.out, max_bytes=110_000)
    print("ok", file=sys.stderr)


def _slice_tiles(path: str, max_tiles: int) -> None:
    """全域スクショを縦タイルに分割して <out>.tile01.jpg ... で保存する。

    各タイルは文字が読める解像度（幅1024）を保ちつつ、1枚ずつが
    data channel 上限に収まるサイズ（110KB以下）になるよう圧縮する。
    """
    from PIL import Image

    img = Image.open(path).convert("RGB")
    width = 1024
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    tile_h = 1100
    n = min(max_tiles, max(1, -(-img.height // tile_h)))
    # 上限枚数を超える高さのページは、収まるようタイル高を伸ばす（解像度は維持）
    tile_h = -(-img.height // n)
    import os

    for i in range(n):
        top = i * tile_h
        tile = img.crop((0, top, img.width, min(top + tile_h, img.height)))
        out = f"{path}.tile{i + 1:02d}.jpg"
        for q in (75, 60, 50, 40):
            tile.save(out, "JPEG", quality=q, optimize=True)
            if os.path.getsize(out) <= 110_000:
                break
    print(f"tiles={n}", file=sys.stderr)


def _shrink_to_fit(path: str, max_bytes: int) -> None:
    import os

    if os.path.getsize(path) <= max_bytes:
        return
    from PIL import Image

    img = Image.open(path).convert("RGB")
    for width, quality in [(800, 60), (720, 50), (640, 45), (560, 40), (480, 35)]:
        if img.width > width:
            resized = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
        else:
            resized = img
        resized.save(path, "JPEG", quality=quality, optimize=True)
        if os.path.getsize(path) <= max_bytes:
            return


if __name__ == "__main__":
    main()
