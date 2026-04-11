"""
吉川特装 HP提案動画 — Playwright録画スクリプト v2
カーソルなし。各セクションに十分な滞在時間。
"""
import asyncio
from playwright.async_api import async_playwright
import os
import shutil

OUT_DIR = os.path.join(os.path.dirname(__file__), "frames")
WIDTH = 1920
HEIGHT = 1080
FPS = 30


async def record():
    if os.path.exists(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR)

    frame_idx = 0

    async def capture(n=1):
        nonlocal frame_idx
        for _ in range(n):
            await page.screenshot(path=os.path.join(OUT_DIR, f"f_{frame_idx:05d}.png"))
            frame_idx += 1

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})

        # ===== Part A: Google検索トップ =====
        print(f"Part A: Google検索 (frame {frame_idx})")
        await page.goto("about:blank")
        await page.set_content("""
        <html><head><style>
            body { margin: 0; background: #fff; font-family: Arial, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; }
            .logo { font-size: 92px; margin-bottom: 30px; }
            .logo span:nth-child(1) { color: #4285f4; } .logo span:nth-child(2) { color: #ea4335; }
            .logo span:nth-child(3) { color: #fbbc05; } .logo span:nth-child(4) { color: #4285f4; }
            .logo span:nth-child(5) { color: #34a853; } .logo span:nth-child(6) { color: #ea4335; }
            .search-box { width: 584px; height: 46px; border: 1px solid #dfe1e5; border-radius: 24px; display: flex; align-items: center; padding: 0 16px; box-shadow: 0 1px 6px rgba(32,33,36,.28); }
            .search-box input { border: none; outline: none; font-size: 16px; flex: 1; margin-left: 8px; }
        </style></head><body>
            <div class="logo"><span>G</span><span>o</span><span>o</span><span>g</span><span>l</span><span>e</span></div>
            <div class="search-box"><span style="color:#9aa0a6;font-size:20px">🔍</span><input id="search" type="text" /></div>
        </body></html>
        """)
        await asyncio.sleep(0.5)
        await capture(45)  # 1.5秒 空の検索画面

        # タイピング
        search_input = await page.query_selector("#search")
        for char in "吉川特装自動車":
            await search_input.type(char, delay=0)
            await asyncio.sleep(0.03)
            await capture(5)  # 各文字 ~0.17秒
        await capture(20)  # 入力完了後0.67秒

        # ===== Part B: 検索結果 =====
        print(f"Part B: 検索結果 (frame {frame_idx})")
        await page.set_content("""
        <html><head><style>
            body { margin: 0; background: #fff; font-family: Arial, sans-serif; }
            .header { background: #fff; border-bottom: 1px solid #ebebeb; padding: 12px 24px; display: flex; align-items: center; gap: 16px; }
            .header-logo span:nth-child(1) { color: #4285f4; } .header-logo span:nth-child(2) { color: #ea4335; }
            .header-logo span:nth-child(3) { color: #fbbc05; } .header-logo span:nth-child(4) { color: #4285f4; }
            .header-logo span:nth-child(5) { color: #34a853; } .header-logo span:nth-child(6) { color: #ea4335; }
            .header-logo { font-size: 28px; }
            .header-search { width: 500px; height: 40px; border: 1px solid #dfe1e5; border-radius: 20px; padding: 0 16px; font-size: 14px; display: flex; align-items: center; }
            .results { padding: 20px 24px 20px 180px; }
            .result { margin-bottom: 28px; }
            .result-url { font-size: 14px; color: #202124; } .result-url small { color: #5f6368; }
            .result-title { font-size: 20px; color: #1a0dab; text-decoration: none; display: block; margin: 4px 0; }
            .result-desc { font-size: 14px; color: #4d5156; line-height: 1.58; }
        </style></head><body>
            <div class="header">
                <div class="header-logo"><span>G</span><span>o</span><span>o</span><span>g</span><span>l</span><span>e</span></div>
                <div class="header-search">吉川特装自動車</div>
            </div>
            <div class="results">
                <div class="result">
                    <div class="result-url">yoshikawa-tokuso.vercel.app<br><small>https://yoshikawa-tokuso.vercel.app</small></div>
                    <a class="result-title" id="main-result">吉川特装自動車 | 鳥取県の新明和認定サービス工場</a>
                    <div class="result-desc">鳥取県の新明和認定サービス工場。ダンプカー、タンクローリー、パワーゲートなど特装車の修理・整備・架装を行っています。36年の実績と確かな技術で対応。</div>
                </div>
                <div class="result">
                    <div class="result-url">example.com<br><small>https://example.com/yoshikawa</small></div>
                    <a class="result-title">吉川特装自動車 - 企業情報</a>
                    <div class="result-desc">吉川特装自動車の企業情報、所在地、営業時間等をご案内しています。</div>
                </div>
            </div>
        </body></html>
        """)
        await asyncio.sleep(0.3)
        await capture(75)  # 2.5秒 検索結果を見せる

        # ===== Part C: HP全体をゆっくりスクロール =====
        print(f"Part C: HP (frame {frame_idx})")
        await page.goto("https://yoshikawa-tokuso.vercel.app", wait_until="networkidle")
        await asyncio.sleep(2)

        # 遅延読み込みトリガー
        height = await page.evaluate("document.body.scrollHeight")
        for pos in range(0, int(height), 500):
            await page.evaluate(f"window.scrollTo(0, {pos})")
            await asyncio.sleep(0.1)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)

        # ヒーロー静止: 4秒
        await capture(120)

        # ゆっくりスクロール: 選ばれる理由まで（y≈1200）
        print(f"  Scroll to 選ばれる理由 (frame {frame_idx})")
        for i in range(120):
            pos = int(1200 * (i / 119))
            await page.evaluate(f"window.scrollTo(0, {pos})")
            await capture(1)
        # 選ばれる理由で停止: 2秒
        await capture(60)

        # サービス一覧までスクロール（y≈1850）
        print(f"  Scroll to サービス (frame {frame_idx})")
        for i in range(90):
            pos = int(1200 + 650 * (i / 89))
            await page.evaluate(f"window.scrollTo(0, {pos})")
            await capture(1)
        # サービス一覧で停止: 2秒
        await capture(60)

        # 対応車種までスクロール（y≈2800）
        print(f"  Scroll to 対応車種 (frame {frame_idx})")
        for i in range(90):
            pos = int(1850 + 950 * (i / 89))
            await page.evaluate(f"window.scrollTo(0, {pos})")
            await capture(1)
        # 対応車種で停止: 2秒
        await capture(60)

        # お問い合わせまでスクロール（y≈3850）
        print(f"  Scroll to お問い合わせ (frame {frame_idx})")
        for i in range(90):
            pos = int(2800 + 1050 * (i / 89))
            await page.evaluate(f"window.scrollTo(0, {pos})")
            await capture(1)
        # お問い合わせで停止: 3秒
        await capture(90)

        # フッターまで（最下部）
        print(f"  Scroll to フッター (frame {frame_idx})")
        scrollable = int(height) - HEIGHT
        for i in range(60):
            pos = int(3850 + (scrollable - 3850) * (i / 59))
            await page.evaluate(f"window.scrollTo(0, {pos})")
            await capture(1)
        # フッターで停止: 1.5秒
        await capture(45)

        print(f"Recording done: {frame_idx} frames ({frame_idx/FPS:.1f}s)")
        await browser.close()


asyncio.run(record())
