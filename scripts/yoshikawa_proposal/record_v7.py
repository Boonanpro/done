"""
吉川特装 HP提案動画 v7
- scroll_if_needed: 画面内にあればスクロールしない
- セクション移動時は100px余白確保
- 車種選択あり
- SE用イベント記録
"""
import asyncio
from playwright.async_api import async_playwright
import os, shutil, json

OUT_DIR = os.path.join(os.path.dirname(__file__), "frames_v7")
W, H, FPS = 1920, 1080, 30

mouse_positions = []
current_mouse = [-100, -100]
events = []


async def main():
    global current_mouse
    if os.path.exists(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR)

    frame_idx = 0

    async def capture(n=1):
        nonlocal frame_idx
        for _ in range(n):
            await page.screenshot(path=os.path.join(OUT_DIR, f"f_{frame_idx:05d}.png"))
            mouse_positions.append(tuple(current_mouse))
            frame_idx += 1

    async def is_in_view(el):
        """要素が画面内に十分見えているか"""
        box = await el.bounding_box()
        if not box:
            return False
        return box["y"] >= 20 and box["y"] + box["height"] <= H - 20

    async def smooth_scroll_to_element(el, margin=100, steps=50):
        """要素まで滑らかにスクロール（余白付き）"""
        current_y = await page.evaluate("window.scrollY")
        target_y = await el.evaluate("el => el.getBoundingClientRect().top + window.scrollY")
        target_y = max(0, target_y - margin)

        if abs(current_y - target_y) < 30:
            return  # ほぼ同じ位置ならスクロール不要

        for i in range(steps):
            t = (i + 1) / steps
            t = t * t * (3 - 2 * t)
            y = current_y + (target_y - current_y) * t
            await page.evaluate(f"window.scrollTo(0, {int(y)})")
            await capture()

    async def scroll_if_needed(selector=None, text=None, margin=100, steps=50):
        """要素が画面外なら滑らかにスクロール、画面内ならスキップ"""
        if text:
            el = await page.query_selector(f'text={text}')
        else:
            el = await page.query_selector(selector)
        if not el:
            print(f"  WARNING: not found: {selector or text}")
            return el
        if not await is_in_view(el):
            await smooth_scroll_to_element(el, margin, steps)
        return el

    async def move_to(selector=None, text=None, steps=20):
        if text:
            el = await page.query_selector(f'text={text}')
        else:
            el = await page.query_selector(selector)
        if not el:
            return None
        box = await el.bounding_box()
        if not box:
            return None
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        sx, sy = current_mouse if current_mouse[0] >= 0 else [cx + 150, cy + 100]
        for i in range(steps):
            t = (i + 1) / steps
            t = t * t * (3 - 2 * t)
            current_mouse[0] = sx + (cx - sx) * t
            current_mouse[1] = sy + (cy - sy) * t
            await capture()
        return el

    async def click(selector=None, text=None):
        el = await move_to(selector, text)
        if el:
            box = await el.bounding_box()
            events.append({"type": "click", "frame": frame_idx})
            await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            await asyncio.sleep(0.1)
            await capture(5)
        return el

    async def type_in(selector, value):
        # まず画面内か確認、必要ならスクロール
        await scroll_if_needed(selector, margin=150, steps=30)
        el = await click(selector)
        if el:
            events.append({"type": "type_start", "frame": frame_idx})
            for char in value:
                await el.type(char, delay=0)
                await asyncio.sleep(0.03)
                await capture(3)
            events.append({"type": "type_end", "frame": frame_idx})
            await capture(5)

    async def hide():
        current_mouse[0] = -100
        current_mouse[1] = -100

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": W, "height": H})

        # ==========================================
        # シーン 1: HPトップ（3秒）
        # ==========================================
        print(f"Scene 1: HP Top (frame {frame_idx})")
        await page.goto("https://yoshikawa-tokuso.vercel.app", wait_until="networkidle")
        await asyncio.sleep(2)
        h = await page.evaluate("document.body.scrollHeight")
        for pos in range(0, int(h), 500):
            await page.evaluate(f"window.scrollTo(0, {pos})")
            await asyncio.sleep(0.1)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)

        await hide()
        await capture(90)

        # ==========================================
        # シーン 2: 「選ばれる理由」へスクロール
        # ==========================================
        print(f"Scene 2: 選ばれる理由 (frame {frame_idx})")
        await scroll_if_needed(text="選ばれる理由", margin=120, steps=60)
        await capture(75)  # 2.5秒静止

        # ==========================================
        # シーン 3: 「サービス一覧」へスクロール
        # ==========================================
        print(f"Scene 3: サービス一覧 (frame {frame_idx})")
        await scroll_if_needed(text="サービス一覧", margin=120, steps=60)
        await capture(75)

        # ==========================================
        # シーン 4: 「対応車種」へスクロール
        # ==========================================
        print(f"Scene 4: 対応車種 (frame {frame_idx})")
        await scroll_if_needed(text="対応車種", margin=120, steps=60)
        await capture(60)

        # ==========================================
        # シーン 5: 「お問い合わせ」へスクロール → ナビクリック
        # ==========================================
        print(f"Scene 5: お問い合わせ (frame {frame_idx})")
        await click(selector='a[href="/contact"]')
        await asyncio.sleep(1)
        await hide()
        await capture(60)

        # ==========================================
        # シーン 6: フォーム入力
        # ==========================================
        print(f"Scene 6: Form (frame {frame_idx})")

        # 会社名
        await type_in('input[name="company"]', "サンプル運送株式会社")

        # お名前
        await type_in('input[name="name"]', "山田太郎")

        # 電話番号
        await type_in('input[name="phone"]', "090-1234-5678")

        # メールアドレス
        await type_in('input[name="email"]', "yamada@sample.co.jp")

        # 車種（セレクト）
        await scroll_if_needed('select[name="vehicle"]', margin=150, steps=20)
        select_el = await move_to('select[name="vehicle"]')
        if select_el:
            events.append({"type": "click", "frame": frame_idx})
            await page.select_option('select[name="vehicle"]', label="ダンプカー")
            await asyncio.sleep(0.1)
            await capture(15)

        # メッセージ
        await type_in('textarea[name="message"]', "ダンプカーの修理をお願いしたいです。")

        # ==========================================
        # シーン 7: 送信ボタン
        # ==========================================
        print(f"Scene 7: Submit (frame {frame_idx})")
        await scroll_if_needed(text="送信する", margin=100, steps=20)
        await move_to(text="送信する")
        events.append({"type": "click", "frame": frame_idx})
        await capture(30)  # ボタン上で1秒停止
        await hide()
        await capture(60)

        print(f"Done: {frame_idx} frames ({frame_idx / FPS:.1f}s)")
        await browser.close()

    # Save
    with open(os.path.join(OUT_DIR, "events.json"), "w") as f:
        json.dump(events, f, indent=2)
    with open(os.path.join(OUT_DIR, "mouse_positions.json"), "w") as f:
        json.dump(mouse_positions, f)
    print(f"Events: {len(events)}, Frames: {len(mouse_positions)}")

    # Cursor composite
    from PIL import Image, ImageDraw
    print("Compositing cursor...")
    size = 28
    for i, (mx, my) in enumerate(mouse_positions):
        if mx < 0 or my < 0:
            continue
        path = os.path.join(OUT_DIR, f"f_{i:05d}.png")
        img = Image.open(path).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        mx, my = int(mx), int(my)
        pts = [
            (mx, my), (mx, my + size),
            (mx + size * 0.3, my + size * 0.75),
            (mx + size * 0.5, my + size * 1.2),
            (mx + size * 0.65, my + size * 1.1),
            (mx + size * 0.4, my + size * 0.65),
            (mx + size * 0.75, my + size * 0.65),
        ]
        for dx, dy in [(-1, -1), (1, 1), (-1, 1), (1, -1)]:
            draw.polygon([(px + dx, py + dy) for px, py in pts], fill=(0, 0, 0, 255))
        draw.polygon(pts, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
        result = Image.alpha_composite(img, overlay)
        result.convert("RGB").save(path)
        if i % 200 == 0:
            print(f"  {i}/{len(mouse_positions)}")
    print("Done!")


asyncio.run(main())
