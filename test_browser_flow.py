"""Test: Full flow - Login -> Send message -> Wait for project creation"""
import asyncio
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.tools.browser import get_executor_page

IMG_PATH = os.path.join(os.environ['TEMP'], 'browser_ss.png')
ELEMS_PATH = os.path.join(os.environ['TEMP'], 'elems.json')

MESSAGE = "noteで月30万円稼ぎたいので、投稿システムを作ってください。あまり執筆に時間をかけたくないので俺が下書きをラフに書いたら、あなたがそれを読んでいて興味を惹く構成に仮清書して、最終的に私が構成して送信ボタンを押したら、ノートに自動で投稿されるようなシステムを作ってほしいです。noteのアカウントも持ってないのでアカウント開設やお金を受け取るところの設定までお願いします。アカウントに使うメールは0aw325171@gmail.comが良いです。"

async def save_screenshot(page, label=""):
    ss = await page.screenshot_base64()
    with open(IMG_PATH, 'wb') as f:
        f.write(base64.b64decode(ss['base64']))
    print(f'[Screenshot] {label}')

async def save_elems(page):
    elems = await page.get_interactive_elements()
    with open(ELEMS_PATH, 'w', encoding='utf-8') as f:
        json.dump(elems, f, ensure_ascii=False, indent=2)
    print(f"  Elements: {len(elems)}")
    return elems


async def main():
    page = await get_executor_page()

    # 1. Navigate
    print("[Step 1] Navigating to localhost:3000...")
    await page.goto('http://localhost:3000')
    await asyncio.sleep(3)
    elems = await save_elems(page)

    # 2. Check if login page - look for email input
    is_login = any(e.get('type') == 'email' for e in elems)

    if is_login:
        print("[Step 2] Login page detected. Logging in...")
        await page.fill_by_ref('@e4', '0aw325171@gmail.com')
        await asyncio.sleep(0.3)
        await page.fill_by_ref('@e5', 'Bold1315')
        await asyncio.sleep(0.3)
        await page.click_by_ref('@e2')
        print("  Clicked login, waiting...")
        await asyncio.sleep(5)
        await save_screenshot(page, "after_login")
        elems = await save_elems(page)
    else:
        print("[Step 2] Already logged in")

    await save_screenshot(page, "logged_in")

    # 3. Find textarea for message input
    print("[Step 3] Finding message textarea...")
    textarea_ref = None
    for e in elems:
        if e.get('tag') == 'textarea':
            textarea_ref = e.get('ref')
            break

    if not textarea_ref:
        print("  No textarea found. Current elements:")
        for e in elems:
            print(f"    {e.get('ref')}: {e.get('tag')} type={e.get('type')} text={e.get('text','')[:50]}")
        print("[ABORT] Cannot proceed without textarea")
        return

    print(f"  Found textarea: {textarea_ref}")

    # 4. Fill and send
    print("[Step 4] Filling message...")
    await page.fill_by_ref(textarea_ref, MESSAGE)
    await asyncio.sleep(1)
    await save_screenshot(page, "message_filled")

    # Find send button - re-scan elements
    elems = await save_elems(page)
    send_ref = None
    for e in elems:
        if e.get('tag') == 'button' and e.get('type') == 'submit':
            send_ref = e.get('ref')
    # Fallback: last button
    if not send_ref:
        buttons = [e for e in elems if e.get('tag') == 'button']
        if buttons:
            send_ref = buttons[-1].get('ref')

    print(f"  Send button: {send_ref}")

    if send_ref:
        print("[Step 5] Sending message...")
        await page.click_by_ref(send_ref)
        await asyncio.sleep(3)
        await save_screenshot(page, "after_send")

        # Wait for AI response (project creation + auto-proposal)
        print("[Step 6] Waiting for AI response (up to 180s)...")
        for i in range(36):
            await asyncio.sleep(5)
            await save_screenshot(page, f"wait_{(i+1)*5}s")
            print(f"  {(i+1)*5}s elapsed...")
    else:
        print("  ERROR: No send button found")

    print("[Done]")


if __name__ == "__main__":
    asyncio.run(main())
