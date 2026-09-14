"""Read-only smoke comparison on public pages using fresh browser contexts."""
import asyncio
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.async_api import async_playwright
from app.tools.browser import _execute_page_command
from app.tools.browser_actions import ref_selector, guarded_click


async def run():
    results = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            for site, url, fragment in [
                ("Amazon Japan", "https://www.amazon.co.jp/s?k=USB+cable", "/dp/"),
                ("Wikipedia Japanese", "https://ja.wikipedia.org/wiki/メインページ", "/wiki/"),
            ]:
                chosen_url = None
                for mode in ["legacy_force", "guarded"]:
                    context = await browser.new_context(locale="ja-JP")
                    page = await context.new_page()
                    started = time.perf_counter()
                    row = {"site": site, "mode": mode, "completed": False, "click_attempts": 0}
                    try:
                        response = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                        await page.wait_for_load_state("load", timeout=15000)
                        row["initial_http_status"] = response.status if response else None
                        await _execute_page_command({"current": page}, context, "get_interactive_elements", {})
                        candidates = await page.evaluate("""fragment => [...document.querySelectorAll('a[data-dan-ref]')]
                          .filter(el => el.href.includes(fragment) && el.href !== location.href && el.innerText.trim() && new URL(el.href).hostname === location.hostname && el.getBoundingClientRect().top >= 0 && el.getBoundingClientRect().top < innerHeight)
                          .map(el => ({ref:el.getAttribute('data-dan-ref'), href:el.href, text:el.innerText.trim().slice(0,80)}))""", fragment)
                        if chosen_url:
                            candidates = [item for item in candidates if item["href"].split('?',1)[0] == chosen_url.split('?',1)[0]]
                        if not candidates:
                            row["limitation"] = "No matching visible public link; access restriction or changed page. Not counted as click success."
                        else:
                            chosen = candidates[0]
                            chosen_url = chosen["href"]
                            row["selected_link"] = chosen["text"]
                            row["click_attempts"] = 1
                            if mode == "legacy_force":
                                await page.locator(ref_selector(chosen["ref"])).click(force=True, timeout=10000)
                                dispatched = True
                            else:
                                outcome = await guarded_click(page, chosen["ref"])
                                dispatched = outcome.get("success", False)
                                row["click_outcome"] = outcome.get("reason", "dispatched")
                                if not dispatched: row["diagnosis"] = outcome
                            if dispatched:
                                await page.wait_for_timeout(500)
                                if len(context.pages) > 1:
                                    page = context.pages[-1]
                                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                                expected = unquote(chosen_url.split("?", 1)[0].split("#", 1)[0])
                                actual = unquote(page.url.split("?", 1)[0].split("#", 1)[0])
                                row["completed"] = actual == expected
                                row["destination_title"] = await page.title()
                                row["destination_matches"] = actual == expected
                    except Exception as exc:
                        row["failure_type"] = type(exc).__name__
                        row["failure"] = str(exc)[:500]
                    finally:
                        row["wall_seconds"] = round(time.perf_counter() - started, 2)
                        results.append(row)
                        print(json.dumps(row, ensure_ascii=True), flush=True)
                        await context.close()
        finally:
            await browser.close()
    path = ROOT / "scratch/browser-public-sites.json"
    path.write_text(json.dumps({"scope": "Read-only fresh-context page navigation; no AI inference, no login, no purchases or form submission. One sample per path, not a site-wide success-rate estimate.", "runs": results}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__": asyncio.run(run())
