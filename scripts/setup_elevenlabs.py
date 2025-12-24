"""
ElevenLabs Account Auto Setup Script
Phase 10 Prep: Automate ElevenLabs account creation and API key retrieval
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


async def setup_elevenlabs():
    """Setup ElevenLabs account"""
    global PASSWORD
    PASSWORD = generate_secure_password()
    
    print("=" * 60)
    print("ElevenLabs Account Auto Setup")
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
            print("[1] Accessing ElevenLabs...")
            await page.goto("https://elevenlabs.io/")
            await page.wait_for_load_state("networkidle")
            
            # Find and click Sign up button
            print("[2] Navigating to signup page...")
            
            signup_selectors = [
                'a:has-text("Sign up")',
                'button:has-text("Sign up")',
                'a:has-text("Get started")',
                'button:has-text("Get started")',
                '[href*="sign-up"]',
                '[href*="signup"]',
            ]
            
            clicked = False
            for selector in signup_selectors:
                try:
                    element = page.locator(selector).first
                    if await element.is_visible(timeout=2000):
                        await element.click()
                        clicked = True
                        print(f"    [OK] Clicked: {selector}")
                        break
                except:
                    continue
            
            if not clicked:
                # Direct access to signup URL
                await page.goto("https://elevenlabs.io/sign-up")
            
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)
            
            # Step 3: Enter email
            print("[3] Entering email address...")
            
            email_selectors = [
                'input[type="email"]',
                'input[name="email"]',
                'input[placeholder*="mail"]',
                'input[placeholder*="Mail"]',
                'input[id*="email"]',
            ]
            
            email_input = None
            for selector in email_selectors:
                try:
                    element = page.locator(selector).first
                    if await element.is_visible(timeout=2000):
                        email_input = element
                        break
                except:
                    continue
            
            if email_input:
                await email_input.fill(EMAIL)
                print("    [OK] Email entered")
            else:
                print("    [WARN] Email input field not found")
                print("    Current URL:", page.url)
                await page.screenshot(path="elevenlabs_debug_1.png")
                print("    Screenshot saved: elevenlabs_debug_1.png")
            
            # Step 4: Enter password
            print("[4] Entering password...")
            
            password_selectors = [
                'input[type="password"]',
                'input[name="password"]',
                'input[placeholder*="assword"]',
            ]
            
            password_input = None
            for selector in password_selectors:
                try:
                    element = page.locator(selector).first
                    if await element.is_visible(timeout=2000):
                        password_input = element
                        break
                except:
                    continue
            
            if password_input:
                await password_input.fill(PASSWORD)
                print("    [OK] Password entered")
            else:
                print("    [WARN] Password input field not found")
            
            # Step 5: Click signup button
            print("[5] Clicking signup button...")
            
            submit_selectors = [
                'button[type="submit"]',
                'button:has-text("Sign up")',
                'button:has-text("Create account")',
                'button:has-text("Continue")',
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
                print("    [WARN] Signup button not found")
                await page.screenshot(path="elevenlabs_debug_2.png")
            
            await asyncio.sleep(3)
            
            # Step 6: Wait for email confirmation
            print("\n" + "=" * 60)
            print("[EMAIL] Confirmation email sent!")
            print("=" * 60)
            print(f"\n1. Check your email: {EMAIL}")
            print("2. Open the email from ElevenLabs")
            print("3. Click the confirmation link in the email")
            print("\n[WAITING] Waiting for email confirmation...")
            print("          (Return to browser after confirmation)")
            
            # Wait for user confirmation
            # Consider complete when redirected to dashboard
            max_wait = 300  # Wait 5 minutes
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                current_url = page.url
                if "app" in current_url or "dashboard" in current_url or "workspace" in current_url:
                    print("\n[SUCCESS] Account confirmed! Dashboard accessed.")
                    break
                await asyncio.sleep(2)
            else:
                print("\n[TIMEOUT] Please complete email confirmation manually")
            
            # Step 7: Get API key
            print("\n[7] Retrieving API key...")
            
            # Navigate to API keys page
            await page.goto("https://elevenlabs.io/app/settings/api-keys")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)
            
            # Find API key
            api_key = None
            
            # Click show key button
            show_key_selectors = [
                'button:has-text("Show")',
                'button:has-text("Reveal")',
                'button:has-text("Copy")',
                '[data-testid*="api-key"]',
            ]
            
            for selector in show_key_selectors:
                try:
                    element = page.locator(selector).first
                    if await element.is_visible(timeout=2000):
                        await element.click()
                        await asyncio.sleep(1)
                        break
                except:
                    continue
            
            # Get API key text
            key_selectors = [
                'input[value*="sk_"]',
                'code:has-text("sk_")',
                'span:has-text("sk_")',
                '[class*="api-key"]',
            ]
            
            for selector in key_selectors:
                try:
                    element = page.locator(selector).first
                    if await element.is_visible(timeout=2000):
                        text = await element.text_content() or await element.get_attribute("value")
                        if text and "sk_" in text:
                            api_key = text.strip()
                            break
                except:
                    continue
            
            # Display results
            print("\n" + "=" * 60)
            print("[COMPLETE] ElevenLabs Setup Complete!")
            print("=" * 60)
            print(f"\nEmail: {EMAIL}")
            print(f"Password: {PASSWORD}")
            if api_key:
                print(f"API Key: {api_key}")
            else:
                print("\n[WARN] Could not auto-retrieve API key.")
                print("       Please get it manually:")
                print("       https://elevenlabs.io/app/settings/api-keys")
            
            print("\n[ENV] Add to .env file:")
            print("-" * 40)
            print(f"ELEVENLABS_API_KEY={api_key or 'YOUR_API_KEY_HERE'}")
            print("-" * 40)
            
            # Save screenshot
            await page.screenshot(path="elevenlabs_final.png")
            print("\n[SCREENSHOT] Final screen: elevenlabs_final.png")
            
            # Keep browser open for user verification
            print("\n[WAIT] Browser is open. Press Enter to close...")
            input()
            
        except Exception as e:
            print(f"\n[ERROR] An error occurred: {e}")
            await page.screenshot(path="elevenlabs_error.png")
            print("        Error screenshot: elevenlabs_error.png")
            raise
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(setup_elevenlabs())
