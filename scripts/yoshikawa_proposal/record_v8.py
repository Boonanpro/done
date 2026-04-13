"""
吉川特装 HP提案動画 v8
- グループ全体が見えるかでスクロール判断
- 無駄なスクロール排除
- タイピング音SE用のイベント記録
"""
import asyncio
from playwright.async_api import async_playwright
import os, shutil, json

OUT_DIR = os.path.join(os.path.dirname(__file__), "frames_v8")
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

    async def get_element(selector=None, text=None):
        if text:
            return await page.query_selector(f'text={text}')
        return await page.query_selector(selector)

    async def smooth_scroll_to_y(target_y, steps=50):
        """指定Y座標まで滑らかにスクロール"""
        current_y = await page.evaluate("window.scrollY")
        if abs(current_y - target_y) < 30:
            return
        for i in range(steps):
            t = (i + 1) / steps
            t = t * t * (3 - 2 * t)
            y = current_y + (target_y - current_y) * t
            await page.evaluate(f"window.scrollTo(0, {int(y)})")
            await capture()

    async def scroll_to_show_element(selector=None, text=None, margin=100, steps=50):
        """1つの要素が画面内に見えるようにスクロール"""
        el = await get_element(selector, text)
        if not el:
            print(f"  WARNING: not found: {selector or text}")
            return
        box = await el.bounding_box()
        if not box:
            return
        # 画面内に十分見えているか
        if box["y"] >= 20 and box["y"] + box["height"] <= H - 20:
            return  # 見えている
        target_y = await el.evaluate("el => el.getBoundingClientRect().top + window.scrollY")
        await smooth_scroll_to_y(max(0, target_y - margin), steps)

    async def scroll_to_show_group(selectors, margin=80, steps=50):
        """複数の要素が全て画面内に収まるようにスクロール"""
        top = float('inf')
        bottom = 0
        for sel in selectors:
            el = await page.query_selector(sel)
            if not el:
                continue
            abs_top = await el.evaluate("el => el.getBoundingClientRect().top + window.scrollY")
            abs_bottom = await el.evaluate("el => el.getBoundingClientRect().bottom + window.scrollY")
            top = min(top, abs_top)
            bottom = max(bottom, abs_bottom)

        if top == float('inf'):
            return

        group_height = bottom - top
        if group_height > H - margin * 2:
            # グループが画面に収まらない場合、上端を基準にスクロール
            target_y = top - margin
        else:
            # 収まる場合、グループが画面中央に来るように
            target_y = top - (H - group_height) / 2

        current_y = await page.evaluate("window.scrollY")
        # 全要素が既に画面内か確認
        all_visible = True
        for sel in selectors:
            el = await page.query_selector(sel)
            if el:
                box = await el.bounding_box()
                if box and (box["y"] < 20 or box["y"] + box["height"] > H - 20):
                    all_visible = False
                    break
        if all_visible:
            return  # 全部見えてる

        await smooth_scroll_to_y(max(0, target_y), steps)

    async def move_to(selector=None, text=None, steps=20):
        el = await get_element(selector, text)
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
        el = await click(selector)
        if el:
            events.append({"type": "type_start", "frame": frame_idx})
            for char in value:
                await el.type(char, delay=0)
                await asyncio.sleep(0.03)
                await capture(3)
            events.append({"type": "type_end", "frame": frame_idx})
            await capture(5)

    async def select_option(selector, label):
        el = await move_to(selector)
        if el:
            events.append({"type": "click", "frame": frame_idx})
            await page.select_option(selector, label=label)
            await asyncio.sleep(0.1)
            await capture(15)

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
        # シーン 2: 「選ばれる理由」
        # ==========================================
        print(f"Scene 2: 選ばれる理由 (frame {frame_idx})")
        await scroll_to_show_element(text="選ばれる理由", margin=120, steps=60)
        await capture(75)

        # ==========================================
        # シーン 3: 「サービス一覧」
        # ==========================================
        print(f"Scene 3: サービス一覧 (frame {frame_idx})")
        await scroll_to_show_element(text="サービス一覧", margin=120, steps=60)
        await capture(75)

        # ==========================================
        # シーン 4: 「対応車種」
        # ==========================================
        print(f"Scene 4: 対応車種 (frame {frame_idx})")
        await scroll_to_show_element(text="対応車種", margin=120, steps=60)
        await capture(60)

        # ==========================================
        # シーン 5: ナビの「お問い合わせ」クリック
        # ==========================================
        print(f"Scene 5: お問い合わせ (frame {frame_idx})")
        await click(selector='a[href="/contact"]')
        await asyncio.sleep(1)
        await hide()
        await capture(60)

        # ==========================================
        # シーン 6: フォーム全体が見える位置にスクロール
        # ==========================================
        print(f"Scene 6: Form (frame {frame_idx})")

        # フォームの全要素が見えるようにスクロール
        await scroll_to_show_group([
            'input[name="company"]',
            'input[name="name"]',
            'input[name="phone"]',
            'input[name="email"]',
            'select[name="vehicle"]',
            'textarea[name="message"]',
            'button',
        ], margin=40, steps=40)
        await capture(30)  # フォーム全体を1秒見せる

        # 入力開始（もうスクロール不要のはず）
        await type_in('input[name="company"]', "サンプル運送株式会社")
        await type_in('input[name="name"]', "山田太郎")
        await type_in('input[name="phone"]', "090-1234-5678")
        await type_in('input[name="email"]', "yamada@sample.co.jp")
        await select_option('select[name="vehicle"]', "ダンプカー")
        await type_in('textarea[name="message"]', "ダンプカーの修理をお願いしたいです。")

        # ==========================================
        # シーン 7: 送信ボタン
        # ==========================================
        print(f"Scene 7: Submit (frame {frame_idx})")
        await move_to(text="送信する")
        events.append({"type": "click", "frame": frame_idx})
        await capture(30)
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
