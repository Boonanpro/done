"""
吉川特装 HP提案動画 — 録画スクリプト

設計書: D:/done/docs/proposals/yoshikawa_scenes.md
各シーンの "操作の流れ" を忠実に実行する。
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

    # ==========================================
    # シーン 1: トップページ概観 (0-6s)
    # ==========================================
    print("[v9] scene 1: top page", flush=True)
    await rec.scroll_to_top()
    await rec.wait(4.0)

    # ==========================================
    # シーン 2: サービス一覧 (6-12s)
    # ==========================================
    print("[v9] scene 2: services", flush=True)
    await rec.scroll_to(text="サービス一覧", margin=80, steps=60)
    await rec.wait(5.0)

    # ==========================================
    # シーン 3: 対応車種 (12-18s)
    # ==========================================
    print("[v9] scene 3: vehicles", flush=True)
    await rec.scroll_to(text="対応車種", margin=80, steps=60)
    await rec.wait(5.0)

    # ==========================================
    # シーン 4: ナビから /contact へ遷移 (18-23s)
    # ==========================================
    print("[v9] scene 4: nav click", flush=True)
    await rec.scroll_to_top(steps=50)
    await rec.click(selector='a[href="/contact"]')
    await rec.wait(2.0)

    # ==========================================
    # シーン 5: フォーム入力 (23-39s)
    # ==========================================
    # A 案: セッション開始時に全フィールドが viewport に収まるよう1回だけスクロール。
    # 以降は固定されたビューのまま、カーソルだけが各フィールドを移動して入力。
    print("[v9] scene 5: form input", flush=True)
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
    await rec.wait(1.0)  # フォーム全体の引きの絵を見せる

    await rec.type(selector='input[name="company"]', value="サンプル運送株式会社")
    await rec.type(selector='input[name="name"]', value="山田太郎")
    await rec.type(selector='input[name="phone"]', value="090-1234-5678")
    await rec.type(selector='input[name="email"]', value="yamada@sample.co.jp")
    await rec.select_option(selector='select[name="vehicle"]', label="ダンプカー")
    await rec.type(selector='textarea[name="message"]', value="ダンプカーの修理をお願いしたいです。")

    # ==========================================
    # シーン 6: 送信 (39-45s)
    # ==========================================
    print("[v9] scene 6: submit", flush=True)
    await rec.click(text="送信する")
    await rec.wait(3.0)

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
