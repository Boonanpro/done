"""
吉川特装 HP提案動画 v6
- 全操作をquery_selector+bounding_boxで実座標取得
- スクロールはscroll_into_viewで正確に（瞬間移動禁止、smooth scroll）
- ズームなし
- クリック/タイプのフレーム番号を記録（SE用）
"""
import asyncio
from playwright.async_api import async_playwright
import os, shutil, json

OUT_DIR = os.path.join(os.path.dirname(__file__), "frames_v6")
W, H, FPS = 1920, 1080, 30

mouse_positions = []
current_mouse = [-100, -100]  # hidden by default
events = []  # {"type": "click"|"type_start"|"type_end", "frame": N}


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

    async def smooth_scroll_to(selector=None, text=None, steps=60):
        """要素までスムーズにスクロール（瞬間移動禁止）"""
        if text:
            el = await page.query_selector(f'text={text}')
        else:
            el = await page.query_selector(selector)
        if not el:
            print(f"  WARNING: scroll target not found: {selector or text}")
            return

        # Get current and target scroll positions
        current_y = await page.evaluate("window.scrollY")
        target_y = await el.evaluate("el => el.getBoundingClientRect().top + window.scrollY - 100")

        for i in range(steps):
            t = (i + 1) / steps
            t = t * t * (3 - 2 * t)  # ease
            y = current_y + (target_y - current_y) * t
            await page.evaluate(f"window.scrollTo(0, {int(y)})")
            await capture()

    async def move_to(selector=None, text=None, steps=20):
        """UI要素にカーソルを移動（表示する）"""
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
        sx, sy = current_mouse if current_mouse[0] >= 0 else [cx + 200, cy + 150]
        for i in range(steps):
            t = (i + 1) / steps
            t = t * t * (3 - 2 * t)
            current_mouse[0] = sx + (cx - sx) * t
            current_mouse[1] = sy + (cy - sy) * t
            await capture()
        return el

    async def click(selector=None, text=None):
        """要素にカーソル移動→クリック"""
        el = await move_to(selector, text)
        if el:
            box = await el.bounding_box()
            events.append({"type": "click", "frame": frame_idx})
            await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            await asyncio.sleep(0.1)
            await capture(5)  # click reaction
        return el

    async def type_in(selector, value):
        """要素をクリックして文字入力"""
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
        # シーン 1: HPトップ表示（3秒）
        # ==========================================
        print(f"Scene 1: HP Top (frame {frame_idx})")
        await page.goto("https://yoshikawa-tokuso.vercel.app", wait_until="networkidle")
        await asyncio.sleep(2)
        # Lazy load trigger
        h = await page.evaluate("document.body.scrollHeight")
        for pos in range(0, int(h), 500):
            await page.evaluate(f"window.scrollTo(0, {pos})")
            await asyncio.sleep(0.1)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)

        await hide()
        await capture(90)  # 3秒ヒーロー

        # ==========================================
        # シーン 2: 「選ばれる理由」までスクロール（2秒スクロール + 2秒静止）
        # ==========================================
        print(f"Scene 2: Scroll to 選ばれる理由 (frame {frame_idx})")
        await smooth_scroll_to(text="選ばれる理由", steps=60)
        await capture(60)  # 2秒静止

        # ==========================================
        # シーン 3: 「サービス一覧」までスクロール（2秒スクロール + 2秒静止）
        # ==========================================
        print(f"Scene 3: Scroll to サービス一覧 (frame {frame_idx})")
        await smooth_scroll_to(text="サービス一覧", steps=60)
        await capture(60)

        # ==========================================
        # シーン 4: 「対応車種」までスクロール（2秒スクロール + 1.5秒静止）
        # ==========================================
        print(f"Scene 4: Scroll to 対応車種 (frame {frame_idx})")
        await smooth_scroll_to(text="対応車種", steps=60)
        await capture(45)

        # ==========================================
        # シーン 5: ナビの「お問い合わせ」をクリック
        # ==========================================
        print(f"Scene 5: Click お問い合わせ (frame {frame_idx})")
        await click(selector='a[href="/contact"]')
        await asyncio.sleep(1)
        await hide()
        await capture(60)  # 2秒 お問い合わせページ表示

        # ==========================================
        # シーン 6: フォーム入力
        # ==========================================
        print(f"Scene 6: Form input (frame {frame_idx})")
        # フォームが見えるようにスクロール
        await smooth_scroll_to(text="お問い合わせフォーム", steps=30)
        await capture(15)

        await type_in('input[name="company"]', "サンプル運送株式会社")
        await type_in('input[name="name"]', "山田太郎")
        await type_in('input[name="phone"]', "090-1234-5678")
        await type_in('input[name="email"]', "yamada@sample.co.jp")

        # メッセージ欄まで
        await smooth_scroll_to('textarea[name="message"]', steps=30)
        await capture(10)
        await type_in('textarea[name="message"]', "ダンプカーの修理をお願いしたいです。")

        # ==========================================
        # シーン 7: 送信ボタンをクリック
        # ==========================================
        print(f"Scene 7: Submit (frame {frame_idx})")
        await smooth_scroll_to(text="送信する", steps=20)
        await capture(10)
        # 送信ボタンにカーソル移動（クリックはしない。実際に送信されてしまうため）
        await move_to(text="送信する")
        events.append({"type": "click", "frame": frame_idx})
        await capture(30)  # ボタン上で1秒停止（クリックしたように見せる）
        await hide()
        await capture(60)  # 2秒 完了

        print(f"Done: {frame_idx} frames ({frame_idx / FPS:.1f}s)")
        await browser.close()

    # Save events
    with open(os.path.join(OUT_DIR, "events.json"), "w") as f:
        json.dump(events, f, indent=2)
    print(f"Events saved: {len(events)} events")

    # Save mouse positions
    with open(os.path.join(OUT_DIR, "mouse_positions.json"), "w") as f:
        json.dump(mouse_positions, f)

    # Composite cursor
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
        points = [
            (mx, my), (mx, my + size),
            (mx + size * 0.3, my + size * 0.75),
            (mx + size * 0.5, my + size * 1.2),
            (mx + size * 0.65, my + size * 1.1),
            (mx + size * 0.4, my + size * 0.65),
            (mx + size * 0.75, my + size * 0.65),
        ]
        for dx, dy in [(-1, -1), (1, 1), (-1, 1), (1, -1)]:
            draw.polygon([(px + dx, py + dy) for px, py in points], fill=(0, 0, 0, 255))
        draw.polygon(points, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
        result = Image.alpha_composite(img, overlay)
        result.convert("RGB").save(path)
        if i % 200 == 0:
            print(f"  {i}/{len(mouse_positions)}")
    print("Done!")


asyncio.run(main())
