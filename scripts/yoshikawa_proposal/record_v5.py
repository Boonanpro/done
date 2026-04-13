"""
吉川特装 HP提案動画 v5 — query_selector操作、シーン設計書準拠
全操作をUI要素の実座標で行う。座標の手書き・推測なし。
"""
import asyncio
from playwright.async_api import async_playwright
import os, shutil

OUT_DIR = os.path.join(os.path.dirname(__file__), "frames_v5")
W, H, FPS = 1920, 1080, 30

mouse_positions = []  # [(x, y)] for cursor compositing
current_mouse = [W // 2, H // 2]


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

    async def move_to_element(selector, text=None):
        """UI要素をquery_selectorで見つけて座標を取得し、カーソルを移動"""
        if text:
            el = await page.query_selector(f'text={text}')
        else:
            el = await page.query_selector(selector)
        if not el:
            print(f"  WARNING: element not found: {selector or text}")
            return None
        box = await el.bounding_box()
        if not box:
            return None
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        # Smooth move
        steps = 20
        sx, sy = current_mouse
        for i in range(steps):
            t = (i + 1) / steps
            t = t * t * (3 - 2 * t)  # ease
            current_mouse[0] = sx + (cx - sx) * t
            current_mouse[1] = sy + (cy - sy) * t
            await capture()
        return el

    async def click_element(selector=None, text=None):
        """要素を見つけて移動→クリック"""
        el = await move_to_element(selector, text)
        if el:
            box = await el.bounding_box()
            await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            await asyncio.sleep(0.1)
        return el

    async def type_in_element(selector, value, delay_per_char=0.05):
        """要素をクリックして文字入力"""
        el = await click_element(selector)
        if el:
            for char in value:
                await el.type(char, delay=0)
                await asyncio.sleep(delay_per_char)
                await capture(3)  # 1文字あたり3フレーム
        return el

    async def hide_cursor():
        current_mouse[0] = -100
        current_mouse[1] = -100

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": W, "height": H})

        # ==========================================
        # シーン 1: HPトップ表示
        # ==========================================
        print(f"Scene 1: HP Top (frame {frame_idx})")
        await page.goto("https://yoshikawa-tokuso.vercel.app", wait_until="networkidle")
        await asyncio.sleep(2)
        # Trigger lazy load
        height = await page.evaluate("document.body.scrollHeight")
        for pos in range(0, int(height), 500):
            await page.evaluate(f"window.scrollTo(0, {pos})")
            await asyncio.sleep(0.1)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)

        await hide_cursor()
        await capture(90)  # 3秒 ヒーロー静止

        # ==========================================
        # シーン 2: ナビゲーションの「サービス」をクリック
        # ==========================================
        print(f"Scene 2: Click サービス (frame {frame_idx})")
        await click_element(text="サービス")
        await asyncio.sleep(0.5)
        await capture(15)  # クリック後の待ち

        await hide_cursor()
        await capture(60)  # 2秒 サービスページ表示

        # ==========================================
        # シーン 3: サービスページをスクロールで見せる
        # ==========================================
        print(f"Scene 3: Scroll services (frame {frame_idx})")
        height = await page.evaluate("document.body.scrollHeight")
        scrollable = height - H
        for i in range(120):
            progress = i / 119
            progress = progress * progress * (3 - 2 * progress)
            await page.evaluate(f"window.scrollTo(0, {int(scrollable * progress * 0.5)})")
            await capture()
        await capture(30)  # 停止

        # ==========================================
        # シーン 4: ナビゲーションの「お問い合わせ」をクリック
        # ==========================================
        print(f"Scene 4: Click お問い合わせ (frame {frame_idx})")
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.3)
        await capture(10)

        await click_element(selector='a[href="/contact"]')
        await asyncio.sleep(1)
        await capture(15)

        await hide_cursor()
        await capture(60)  # 2秒 お問い合わせページ表示

        # ==========================================
        # シーン 5: フォーム入力
        # ==========================================
        print(f"Scene 5: Form input (frame {frame_idx})")
        # スクロールしてフォームが見えるように
        await page.evaluate("window.scrollTo(0, 400)")
        await asyncio.sleep(0.3)
        await capture(15)

        # 会社名
        await type_in_element('input[name="company"]', "サンプル運送株式会社")
        await capture(10)

        # お名前
        await type_in_element('input[name="name"]', "山田太郎")
        await capture(10)

        # 電話番号
        await type_in_element('input[name="phone"]', "090-1234-5678")
        await capture(10)

        # メールアドレス
        await type_in_element('input[name="email"]', "yamada@sample.co.jp")
        await capture(10)

        # メッセージ
        await page.evaluate("window.scrollTo(0, 800)")
        await asyncio.sleep(0.3)
        await capture(10)
        await type_in_element('textarea[name="message"]', "ダンプカーの修理をお願いしたいです。")
        await capture(15)

        # ==========================================
        # シーン 6: 送信ボタンをクリック
        # ==========================================
        print(f"Scene 6: Submit (frame {frame_idx})")
        await page.evaluate("window.scrollTo(0, 1000)")
        await asyncio.sleep(0.3)
        await capture(10)

        # 送信ボタンを見つけてクリック
        submit = await page.query_selector('button')
        if submit:
            box = await submit.bounding_box()
            if box:
                await move_to_element('button')
                await capture(15)  # ボタン上で停止
                await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                await asyncio.sleep(0.5)
                await capture(30)  # 送信後

        await hide_cursor()
        await capture(60)  # 2秒 完了表示

        print(f"Done: {frame_idx} frames ({frame_idx / FPS:.1f}s)")
        await browser.close()

    # Save mouse positions for cursor compositing
    import json
    with open(os.path.join(OUT_DIR, "mouse_positions.json"), "w") as f:
        json.dump(mouse_positions, f)
    print(f"Mouse positions saved: {len(mouse_positions)}")

    # Composite cursor
    from PIL import Image, ImageDraw
    print("Compositing cursor...")
    cursor_size = 28
    for i, (mx, my) in enumerate(mouse_positions):
        if mx < 0 or my < 0:  # Hidden cursor
            if i % 100 == 0:
                print(f"  {i}/{len(mouse_positions)} (hidden)")
            continue
        path = os.path.join(OUT_DIR, f"f_{i:05d}.png")
        img = Image.open(path).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        mx, my = int(mx), int(my)
        s = cursor_size
        points = [
            (mx, my), (mx, my + s),
            (mx + s * 0.3, my + s * 0.75),
            (mx + s * 0.5, my + s * 1.2),
            (mx + s * 0.65, my + s * 1.1),
            (mx + s * 0.4, my + s * 0.65),
            (mx + s * 0.75, my + s * 0.65),
        ]
        # Black outline
        for dx, dy in [(-1, -1), (1, 1), (-1, 1), (1, -1)]:
            draw.polygon([(px + dx, py + dy) for px, py in points], fill=(0, 0, 0, 255))
        draw.polygon(points, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
        result = Image.alpha_composite(img, overlay)
        result.convert("RGB").save(path)
        if i % 100 == 0:
            print(f"  {i}/{len(mouse_positions)}")
    print("Cursor composite done!")


asyncio.run(main())
