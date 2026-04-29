"""Capture Dribbble search results as reference for yoshikawa-v2."""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

REFS = Path("D:/dan-workspace/hp-projects/yoshikawa-v2/refs")
REFS.mkdir(parents=True, exist_ok=True)
USER_DATA = "D:/done/.playwright-dribbble"

SEARCHES = [
    ("https://dribbble.com/search/construction%20website", "dribbble-1-search.png"),
    ("https://dribbble.com/search/industrial%20landing%20page", "dribbble-2-industrial.png"),
    ("https://dribbble.com/search/workshop%20website%20dark", "dribbble-3-workshop.png"),
    ("https://dribbble.com/search/automotive%20garage%20website", "dribbble-4-automotive.png"),
]

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        USER_DATA,
        headless=False,
        viewport={"width": 1440, "height": 900},
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    for url, fname in SEARCHES:
        print(f"[nav] {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"  goto warn: {e}")
        time.sleep(5)
        try:
            page.mouse.wheel(0, 800)
            time.sleep(1)
            page.mouse.wheel(0, -800)
            time.sleep(1)
        except Exception:
            pass
        out = REFS / fname
        page.screenshot(path=str(out), full_page=False)
        print(f"  saved {out}")

    # Detail shots: go back to automotive search and click into shots
    print("[nav] back to automotive for details")
    page.goto("https://dribbble.com/search/automotive%20garage%20website",
              wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)

    detail_count = 0
    # Collect shot links
    links = []
    try:
        import re
        anchors = page.query_selector_all('a[href*="/shots/"]')
        seen = set()
        for a in anchors:
            href = a.get_attribute("href") or ""
            # real shot URLs look like /shots/12345678-title
            if not re.search(r"/shots/\d+", href):
                continue
            if href in seen:
                continue
            seen.add(href)
            if href.startswith("/"):
                href = "https://dribbble.com" + href
            links.append(href)
            if len(links) >= 6:
                break
    except Exception as e:
        print(f"  collect warn: {e}")

    print(f"  found {len(links)} shot links")
    for href in links:
        if detail_count >= 3:
            break
        try:
            print(f"[detail] {href}")
            page.goto(href, wait_until="domcontentloaded", timeout=60000)
            time.sleep(4)
            detail_count += 1
            out = REFS / f"dribbble-detail-{detail_count}.png"
            page.screenshot(path=str(out), full_page=True)
            print(f"  saved {out}")
        except Exception as e:
            print(f"  detail warn: {e}")

    ctx.close()
    print("DONE")
