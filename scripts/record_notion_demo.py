"""Record Notion demo with mouse animation and cursor overlay."""
import asyncio
from playwright.async_api import async_playwright
from PIL import Image, ImageDraw
import os, shutil, json

# Mouse position tracker
mouse_positions = []
current_mouse = [960, 540]

async def record_demo():
    global current_mouse
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})

        out = r"C:\Users\Owner\AppData\Local\Temp\dan_notion_proposal_v2\frames"
        if os.path.exists(out):
            shutil.rmtree(out)
        os.makedirs(out)

        frame_idx = 0

        async def capture(n=1):
            nonlocal frame_idx
            for _ in range(n):
                await page.screenshot(path=f"{out}/f_{frame_idx:05d}.png")
                mouse_positions.append(tuple(current_mouse))
                frame_idx += 1

        async def smooth_move(x1, y1, x2, y2, steps=30):
            nonlocal frame_idx
            global current_mouse
            for i in range(steps):
                t = i / max(steps - 1, 1)
                t = t * t * (3 - 2 * t)
                x = x1 + (x2 - x1) * t
                y = y1 + (y2 - y1) * t
                current_mouse = [x, y]
                await page.mouse.move(x, y)
                await capture()

        await page.goto("http://127.0.0.1:3000/demo/notion", wait_until="networkidle")
        await asyncio.sleep(2)

        # Scene 1: Editor view - hold 3s
        print(f"Scene 1: Editor view (frame {frame_idx})")
        await capture(90)

        # Scene 2: Click sidebar '五条'
        print(f"Scene 2: Sidebar nav (frame {frame_idx})")
        gojo = await page.query_selector("text=OBANZAI bar 五条")
        if gojo:
            box = await gojo.bounding_box()
            if box:
                cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                await smooth_move(960, 540, cx, cy, steps=25)
                await capture(5)
                await page.mouse.click(cx, cy)
                await asyncio.sleep(0.3)
                await capture(30)

        # Scene 3: Click 吉川, switch to Files
        print(f"Scene 3: Files view (frame {frame_idx})")
        yoshi = await page.query_selector("text=吉川特装自動車")
        if yoshi:
            box = await yoshi.bounding_box()
            if box:
                cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                await smooth_move(current_mouse[0], current_mouse[1], cx, cy, steps=15)
                await page.mouse.click(cx, cy)
                await asyncio.sleep(0.3)
                await capture(15)

        files_btn = await page.query_selector("text=ファイル")
        if files_btn:
            box = await files_btn.bounding_box()
            if box:
                cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                await smooth_move(current_mouse[0], current_mouse[1], cx, cy, steps=20)
                await capture(5)
                await page.mouse.click(cx, cy)
                await asyncio.sleep(0.5)
                await capture(60)

        # Scene 4: Hover file cards
        print(f"Scene 4: Hover files (frame {frame_idx})")
        cards = await page.query_selector_all("[class*='rounded-lg'][class*='cursor-pointer']")
        for card in cards[:3]:
            box = await card.bounding_box()
            if box:
                cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                await smooth_move(current_mouse[0], current_mouse[1], cx, cy, steps=15)
                await capture(10)

        # Scene 5: Search
        print(f"Scene 5: Search (frame {frame_idx})")
        search_input = await page.query_selector('input[placeholder="検索..."]')
        if search_input:
            box = await search_input.bounding_box()
            if box:
                cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                await smooth_move(current_mouse[0], current_mouse[1], cx, cy, steps=20)
                await capture(5)
                await page.mouse.click(cx, cy)
                await capture(10)
                for char in "請求書":
                    await search_input.type(char, delay=50)
                    await capture(8)
                await asyncio.sleep(0.5)
                await capture(45)

        # Scene 6: AI Chat
        print(f"Scene 6: AI Chat (frame {frame_idx})")
        if search_input:
            await search_input.fill("")
            await capture(5)

        ai_btn = await page.query_selector("text=ダン AI に聞く")
        if ai_btn:
            box = await ai_btn.bounding_box()
            if box:
                cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                await smooth_move(current_mouse[0], current_mouse[1], cx, cy, steps=20)
                await capture(5)
                await page.mouse.click(cx, cy)
                await asyncio.sleep(0.5)
                await capture(30)

        chat_input = await page.query_selector('input[placeholder="資料について聞く..."]')
        if chat_input:
            box = await chat_input.bounding_box()
            if box:
                cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                await smooth_move(current_mouse[0], current_mouse[1], cx, cy, steps=15)
                await page.mouse.click(cx, cy)
                await capture(5)
                for char in "前回の請求書見せて":
                    await chat_input.type(char, delay=30)
                    await capture(5)
                await capture(15)
                await page.keyboard.press("Enter")
                await asyncio.sleep(2)
                await capture(90)

        # Scene 7: Final hold
        print(f"Scene 7: End (frame {frame_idx})")
        await capture(60)

        total_sec = frame_idx / 30
        print(f"Done: {frame_idx} frames ({total_sec:.1f} seconds)")

        # Save mouse positions
        pos_path = os.path.join(out, "mouse_positions.json")
        with open(pos_path, "w") as f:
            json.dump(mouse_positions, f)
        print(f"Mouse positions saved: {len(mouse_positions)} entries")

        await browser.close()

    # Phase 2: Overlay cursor on all frames
    print("\nOverlaying cursor on frames...")
    cursor_size = 28
    for i, (mx, my) in enumerate(mouse_positions):
        path = f"{out}/f_{i:05d}.png"
        img = Image.open(path).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        mx, my = int(mx), int(my)

        # Standard arrow cursor shape (larger, fully opaque)
        s = cursor_size
        cursor_points = [
            (mx, my),                          # tip
            (mx, my + s),                      # left edge bottom
            (mx + s * 0.3, my + s * 0.75),     # notch left
            (mx + s * 0.5, my + s * 1.2),      # tail right
            (mx + s * 0.65, my + s * 1.1),      # tail right outer
            (mx + s * 0.4, my + s * 0.65),      # notch right
            (mx + s * 0.75, my + s * 0.65),     # right wing
        ]
        # Black outline (draw slightly larger first)
        outline_points = [(px - 1, py - 1) for px, py in cursor_points]
        draw.polygon(outline_points, fill=(0, 0, 0, 255))
        # Shift for thicker outline
        outline_points2 = [(px + 1, py + 1) for px, py in cursor_points]
        draw.polygon(outline_points2, fill=(0, 0, 0, 255))
        # White fill (fully opaque)
        draw.polygon(cursor_points, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))

        result = Image.alpha_composite(img, overlay)
        result.convert("RGB").save(path)
        if i % 100 == 0:
            print(f"  {i}/{len(mouse_positions)}")

    print("Cursor overlay complete!")

asyncio.run(record_demo())
