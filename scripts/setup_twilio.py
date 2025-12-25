"""
Twilio Account Auto Setup Script
Phase 10 Prep: Automate Twilio account creation and API credentials retrieval
"""
import asyncio
import secrets
import string
import time
from playwright.async_api import async_playwright

# Settings
EMAIL = "0aw325171@gmail.com"
PASSWORD = None  # Auto-generated


def generate_secure_password(length: int = 16) -> str:
    """Generate a secure password"""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    # Ensure password contains uppercase, lowercase, digit, and symbol
    password = (
        secrets.choice(string.ascii_uppercase) +
        secrets.choice(string.ascii_lowercase) +
        secrets.choice(string.digits) +
        secrets.choice("!@#$%^&*") +
        password[4:]
    )
    return password


async def setup_twilio():
    """Setup Twilio account"""
    global PASSWORD
    PASSWORD = generate_secure_password()
    
    print("=" * 60)
    print("Twilio Account Auto Setup")
    print("=" * 60)
    print(f"Email: {EMAIL}")
    print(f"Password: {PASSWORD}")
    print("=" * 60)
    print("\n[!] SAVE THIS PASSWORD IN A SECURE LOCATION!\n")
    
    async with async_playwright() as p:
        # Launch browser (headed mode for visibility)
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            # Step 1: Access signup page
            print("[1] Accessing Twilio signup page...")
            await page.goto("https://www.twilio.com/try-twilio", timeout=60000)
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(5)
            
            # Take screenshot for debugging
            await page.screenshot(path="twilio_step1.png")
            print("    Screenshot saved: twilio_step1.png")
            
            # Step 2: Fill signup form
            print("[2] Filling signup form...")
            
            # Email
            email_input = page.locator('input[name="email"], input[type="email"], input[id*="email"]').first
            if await email_input.is_visible(timeout=5000):
                await email_input.fill(EMAIL)
                print("    [OK] Email entered")
            else:
                print("    [WARN] Email field not found")
                await page.screenshot(path="twilio_debug_email.png")
            
            # First Name (if exists)
            first_name = page.locator('input[name="firstName"], input[name="first_name"], input[id*="first"]').first
            try:
                if await first_name.is_visible(timeout=2000):
                    await first_name.fill("AI")
                    print("    [OK] First name entered")
            except:
                pass
            
            # Last Name (if exists)
            last_name = page.locator('input[name="lastName"], input[name="last_name"], input[id*="last"]').first
            try:
                if await last_name.is_visible(timeout=2000):
                    await last_name.fill("Secretary")
                    print("    [OK] Last name entered")
            except:
                pass
            
            # Password
            password_input = page.locator('input[type="password"], input[name="password"]').first
            if await password_input.is_visible(timeout=5000):
                await password_input.fill(PASSWORD)
                print("    [OK] Password entered")
            else:
                print("    [WARN] Password field not found")
            
            # Check for Terms checkbox
            terms_checkbox = page.locator('input[type="checkbox"]').first
            try:
                if await terms_checkbox.is_visible(timeout=2000):
                    if not await terms_checkbox.is_checked():
                        await terms_checkbox.click()
                        print("    [OK] Terms accepted")
            except:
                pass
            
            await page.screenshot(path="twilio_step2.png")
            
            # Step 3: Submit form
            print("[3] Submitting signup form...")
            
            submit_selectors = [
                'button[type="submit"]',
                'button:has-text("Start your free trial")',
                'button:has-text("Sign up")',
                'button:has-text("Create account")',
                'button:has-text("Get started")',
                'input[type="submit"]',
            ]
            
            submitted = False
            for selector in submit_selectors:
                try:
                    element = page.locator(selector).first
                    if await element.is_visible(timeout=2000):
                        await element.click()
                        submitted = True
                        print(f"    [OK] Clicked: {selector}")
                        break
                except:
                    continue
            
            if not submitted:
                print("    [WARN] Submit button not found")
                await page.screenshot(path="twilio_debug_submit.png")
            
            await asyncio.sleep(5)
            await page.screenshot(path="twilio_step3.png")
            
            # Step 4: Handle verification
            print("\n" + "=" * 60)
            print("[VERIFICATION] Email/Phone verification may be required")
            print("=" * 60)
            print(f"\n1. Check your email: {EMAIL}")
            print("2. You may need to verify your phone number")
            print("3. Complete any CAPTCHA if shown")
            print("\n[WAITING] Please complete verification manually...")
            print("          The script will continue when you reach the console.")
            
            # Wait for console page
            max_wait = 600  # 10 minutes
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                current_url = page.url
                if "console" in current_url or "dashboard" in current_url:
                    print("\n[SUCCESS] Console accessed!")
                    break
                await asyncio.sleep(3)
            else:
                print("\n[TIMEOUT] Please complete verification and navigate to console")
            
            await page.screenshot(path="twilio_step4.png")
            
            # Step 5: Get Account SID and Auth Token
            print("\n[5] Retrieving credentials...")
            
            # Navigate to console
            await page.goto("https://console.twilio.com/")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)
            
            await page.screenshot(path="twilio_console.png")
            
            # Try to find Account SID and Auth Token
            account_sid = None
            auth_token = None
            
            # Look for Account SID
            sid_elements = page.locator('text=AC').all()
            
            # Try to get from page content
            page_content = await page.content()
            
            # Look for patterns like AC followed by 32 hex chars
            import re
            sid_match = re.search(r'(AC[a-f0-9]{32})', page_content)
            if sid_match:
                account_sid = sid_match.group(1)
                print(f"    [OK] Found Account SID: {account_sid}")
            
            # Step 6: Get a phone number
            print("\n[6] Attempting to get a phone number...")
            
            # Navigate to phone numbers page
            await page.goto("https://console.twilio.com/us1/develop/phone-numbers/manage/incoming")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)
            
            await page.screenshot(path="twilio_phone_numbers.png")
            
            # Display results
            print("\n" + "=" * 60)
            print("[RESULT] Twilio Setup Progress")
            print("=" * 60)
            print(f"\nEmail: {EMAIL}")
            print(f"Password: {PASSWORD}")
            if account_sid:
                print(f"Account SID: {account_sid}")
            else:
                print("Account SID: [Please check console manually]")
            print("Auth Token: [Please check console manually - click 'Show' button]")
            print("Phone Number: [Please purchase from console if not shown]")
            
            print("\n[MANUAL STEPS]")
            print("1. Go to: https://console.twilio.com/")
            print("2. Find Account SID and Auth Token on the dashboard")
            print("3. Go to Phone Numbers > Buy a Number to get a phone number")
            print("4. Add these to your .env file:")
            print("-" * 40)
            print(f"TWILIO_ACCOUNT_SID={account_sid or 'YOUR_ACCOUNT_SID'}")
            print("TWILIO_AUTH_TOKEN=YOUR_AUTH_TOKEN")
            print("TWILIO_PHONE_NUMBER=+1XXXXXXXXXX")
            print("-" * 40)
            
            # Keep browser open
            print("\n[WAIT] Browser is open for you to complete setup.")
            print("       Press Enter when done to close...")
            
            # Non-blocking wait - just sleep and let user interact
            await asyncio.sleep(300)  # Wait 5 minutes
            
        except Exception as e:
            print(f"\n[ERROR] An error occurred: {e}")
            await page.screenshot(path="twilio_error.png")
            print("        Error screenshot: twilio_error.png")
            raise
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(setup_twilio())

