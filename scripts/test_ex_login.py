"""
SmartEX ログインテスト - OTP画面のセレクタ調査用
"""
import asyncio
import sys
sys.path.insert(0, "D:\\done")

from playwright.async_api import async_playwright
from app.executors.ex_reservation.selectors import URLS, LOGIN, OTP, COMMON
from app.config import settings


def log(msg):
    print(msg, flush=True)


async def dump_page_elements(page):
    """ページの主要要素をダンプ"""
    log("\n" + "=" * 60)
    log("PAGE ELEMENT DUMP")
    log("=" * 60)
    log(f"URL: {page.url}")
    
    # 全てのボタンを列挙
    log("\n--- BUTTONS ---")
    buttons = await page.locator("button").all()
    for i, btn in enumerate(buttons):
        try:
            text = await btn.inner_text()
            log(f"  [{i}] button: '{text.strip()}'")
        except:
            pass
    
    # 全てのinputを列挙
    log("\n--- INPUTS ---")
    inputs = await page.locator("input").all()
    for i, inp in enumerate(inputs):
        try:
            placeholder = await inp.get_attribute("placeholder")
            input_type = await inp.get_attribute("type")
            log(f"  [{i}] input: type='{input_type}', placeholder='{placeholder}'")
        except:
            pass
    
    # 「自動音声」を含む要素を探す
    log("\n--- ELEMENTS WITH '自動音声' ---")
    elements = await page.locator("text=自動音声").all()
    log(f"  Found: {len(elements)} elements")
    for i, el in enumerate(elements):
        try:
            tag = await el.evaluate("el => el.tagName")
            text = await el.inner_text()
            log(f"  [{i}] {tag}: '{text.strip()[:50]}'")
        except:
            pass
    
    # 「ワンタイム」を含む要素を探す
    log("\n--- ELEMENTS WITH 'ワンタイム' ---")
    elements = await page.locator("text=ワンタイム").all()
    log(f"  Found: {len(elements)} elements")
    
    # 「次へ」「OK」を含む要素を探す
    log("\n--- ELEMENTS WITH '次へ' or 'OK' ---")
    elements = await page.locator("text=次へ").all()
    log(f"  '次へ': {len(elements)} elements")
    elements = await page.locator("text=OK").all()
    log(f"  'OK': {len(elements)} elements")
    
    log("\n" + "=" * 60)


async def main():
    member_id = settings.EX_MEMBER_ID
    password = settings.EX_PASSWORD
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        log("=" * 60)
        log("SmartEX Login Test - OTP Selector Investigation")
        log("=" * 60)
        
        # ログインページにアクセス
        log(f"\n1. Open: {URLS['login']}")
        await page.goto(URLS["login"], wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        
        # 会員ID入力
        log(f"\n2. Member ID: {member_id}")
        await page.locator(LOGIN["member_id"]).fill(member_id)
        
        # パスワード入力
        log("\n3. Password: ********")
        await page.locator(LOGIN["password"]).fill(password)
        
        # ログインボタンをクリック
        log("\n4. Click Login button")
        await page.locator(LOGIN["login_button"]).click()
        
        # ページ遷移を待機
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(3000)
        
        log(f"\n5. Current URL: {page.url}")
        
        # ページ要素をダンプ
        await dump_page_elements(page)
        
        # 現在のセレクタでOTP要素を確認
        log("\n--- CHECKING CURRENT OTP SELECTORS ---")
        for name, selector in OTP.items():
            count = await page.locator(selector).count()
            log(f"  {name}: '{selector}' -> {count} found")
        
        log("\n" + "=" * 60)
        log("Browser open. Press Ctrl+C to exit.")
        log("=" * 60)
        
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            log("\nClosing...")
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
