"""
吉川特装 HP提案動画 v9 — 共通 StudioRecorder で撮影

SKILL.md のルールは recorder 側がデフォルトで自動的に守る:
  - 瞬間スクロール禁止 → scroll_to_top / scroll_to_y で滑らかスクロール
  - 無操作時カーソル非表示 → scroll/fit/wait で自動非表示
  - フォーム維持 → 各インタラクション前に _ensure_in_viewport で自動
このファイルは純粋にシーン指示だけ記述する。
"""
import asyncio
import sys
import traceback
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

print("[v9] starting", flush=True)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
print(f"[v9] repo_root={REPO_ROOT}", flush=True)

try:
    from app.services.studio_recorder import StudioRecorder
    print("[v9] imported StudioRecorder", flush=True)
except Exception as e:
    print(f"[v9] IMPORT FAILED: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)


OUT_DIR = Path(__file__).parent / "frames_v9"
URL = "https://yoshikawa-tokuso.vercel.app"


async def main():
    print(f"[v9] creating recorder, output={OUT_DIR}", flush=True)
    rec = StudioRecorder(output_dir=str(OUT_DIR))
    print(f"[v9] launching browser, url={URL}", flush=True)
    await rec.start(URL)
    print("[v9] browser ready", flush=True)

    # シーン 1: トップページ概観
    print("[v9] scene 1 (top overview)", flush=True)
    await rec.scroll_to_top()  # 滑らか + カーソル自動非表示
    page_h = await rec.page.evaluate("document.body.scrollHeight")
    # 下までゆっくりスクロールして戻る
    await rec.scroll_to_y(min(int(page_h) - 500, 3000), steps=60)
    await rec.scroll_to_top(steps=60)
    await rec.wait(2.0)

    # シーン 2: 選ばれる理由
    print("[v9] scene 2 (reasons)", flush=True)
    await rec.scroll_to(text="選ばれる理由", margin=120, steps=60)
    await rec.wait(2.0)

    # シーン 3: サービス一覧
    print("[v9] scene 3 (services)", flush=True)
    await rec.scroll_to(text="サービス一覧", margin=120, steps=60)
    await rec.wait(2.0)

    # シーン 4: 対応車種
    print("[v9] scene 4 (vehicles)", flush=True)
    await rec.scroll_to(text="対応車種", margin=120, steps=60)
    await rec.wait(2.0)

    # シーン 5: ナビの「お問い合わせ」をクリック
    # トップに滑らか戻ってからクリック
    print("[v9] scene 5 (nav click)", flush=True)
    await rec.scroll_to_top(steps=60)
    await rec.click(selector='a[href="/contact"]')
    await rec.wait(1.5)  # 遷移後の静止

    # シーン 6: フォーム全体を収めてから入力
    print("[v9] scene 6 (form input)", flush=True)
    await rec.fit_elements_in_viewport(
        [
            'input[name="company"]',
            'input[name="name"]',
            'input[name="phone"]',
            'input[name="email"]',
            'select[name="vehicle"]',
            'textarea[name="message"]',
            'button',
        ],
        margin=40,
    )
    await rec.wait(1.0)

    await rec.type(selector='input[name="company"]', value="サンプル運送株式会社")
    await rec.type(selector='input[name="name"]', value="山田太郎")
    await rec.type(selector='input[name="phone"]', value="090-1234-5678")
    await rec.type(selector='input[name="email"]', value="yamada@sample.co.jp")
    await rec.select_option(selector='select[name="vehicle"]', label="ダンプカー")
    await rec.type(selector='textarea[name="message"]', value="ダンプカーの修理をお願いしたいです。")

    # シーン 7: 送信ボタン
    print("[v9] scene 7 (submit)", flush=True)
    await rec.click(text="送信する")
    await rec.wait(2.0)

    print("[v9] finalizing (composite + encode)", flush=True)
    await rec.finalize(output_name="yoshikawa")
    print("[v9] DONE", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"[v9] RUNTIME FAILED: {e}", flush=True)
        traceback.print_exc()
        sys.exit(2)
