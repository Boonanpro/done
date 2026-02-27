"""
SmartEX ログイン + OTP入力テスト
"""
import asyncio
import sys
sys.path.insert(0, "D:\\done")

from playwright.async_api import async_playwright
from app.executors.ex_reservation.login import login, request_otp, enter_otp, detect_page_state, PageState
from app.executors.ex_reservation.selectors import OTP
from app.config import settings


def log(msg):
    print(msg, flush=True)


async def main():
    member_id = settings.EX_MEMBER_ID
    password = settings.EX_PASSWORD
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        log("=" * 60)
        log("SmartEX Login + OTP Test")
        log("=" * 60)
        
        # ログイン実行
        log("\n1. Executing login()...")
        result = await login(page, member_id, password)
        
        log(f"   - success: {result.success}")
        log(f"   - message: {result.message}")
        log(f"   - requires_otp: {result.requires_otp}")
        log(f"   - page_state: {result.page_state}")
        
        # OTPが必要な場合
        if result.requires_otp or result.page_state == PageState.OTP_REQUIRED:
            log("\n2. OTP Required!")
            
            # OTPセレクタの確認
            log("\n   Checking OTP selectors:")
            for name, selector in OTP.items():
                count = await page.locator(selector).count()
                log(f"     {name}: {count} found")
            
            # OTP発信ボタンをクリック
            log("\n3. Clicking 'send_voice_button'...")
            otp_result = await request_otp(page)
            log(f"   - {otp_result.message}")
            
            log("\n" + "=" * 60)
            log("OTP has been requested!")
            log("Your phone will receive a call with the OTP.")
            log("=" * 60)
            
            # ファイルからOTPを読み取る（ユーザーが書き込む）
            otp_file = "D:\\done\\otp.txt"
            log(f"\nWaiting for OTP...")
            log(f"Write the 6-digit OTP to: {otp_file}")
            log("Example: echo 123456 > D:\\done\\otp.txt")
            
            otp_code = None
            for _ in range(60):  # 60秒待機
                try:
                    with open(otp_file, 'r') as f:
                        otp_code = f.read().strip()
                        if len(otp_code) == 6 and otp_code.isdigit():
                            log(f"\nOTP received: {otp_code}")
                            break
                        otp_code = None
                except FileNotFoundError:
                    pass
                await asyncio.sleep(1)
            
            if otp_code:
                log(f"\n4. Entering OTP: {otp_code}")
                enter_result = await enter_otp(page, otp_code)
                log(f"   - success: {enter_result.success}")
                log(f"   - message: {enter_result.message}")
                
                if enter_result.success:
                    log("\n[OK] Login successful after OTP!")
                else:
                    log(f"\n[ERROR] OTP failed: {enter_result.message}")
            else:
                log("\n[TIMEOUT] No OTP received within 60 seconds")
        
        elif result.success:
            log("\n[OK] Login successful (no OTP required)!")
        
        else:
            log(f"\n[ERROR] Login failed: {result.message}")
        
        log(f"\nFinal URL: {page.url}")
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

