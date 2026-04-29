"""Take screenshots of the Dan HP website at localhost:3001."""
import os
import time
from playwright.sync_api import sync_playwright

OUTPUT_DIR = "D:/dan-workspace/hp-projects/dan"
URL = "http://localhost:3001"

SECTIONS = [
    ("screenshot-hero.png", None),            # top of page
    ("screenshot-features.png", "#features"),
    ("screenshot-portfolio.png", "#portfolio"),
    ("screenshot-services.png", "#services"),
    ("screenshot-contact.png", "#contact"),
]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        print(f"Navigating to {URL} ...")
        page.goto(URL, wait_until="networkidle")
        # Wait for fonts / animations
        time.sleep(2)

        # Full-page screenshot
        full_path = os.path.join(OUTPUT_DIR, "screenshot-full.png")
        page.screenshot(path=full_path, full_page=True)
        print(f"Saved full-page screenshot: {full_path}")

        # Section screenshots (viewport-sized)
        for filename, selector in SECTIONS:
            if selector:
                el = page.query_selector(selector)
                if el:
                    el.scroll_into_view_if_needed()
                    time.sleep(0.5)  # let scroll settle
                else:
                    print(f"WARNING: selector '{selector}' not found, taking screenshot at current scroll position")
            else:
                page.evaluate("window.scrollTo(0, 0)")
                time.sleep(0.3)

            path = os.path.join(OUTPUT_DIR, filename)
            page.screenshot(path=path)
            print(f"Saved: {path}")

        browser.close()
        print("Done.")


if __name__ == "__main__":
    main()
