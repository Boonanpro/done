"""Read-only headless regression check for a cold local chat page.

Requires an existing authorized session file containing a token; never prints
credentials or message content and never attaches to the user's browser.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from playwright.async_api import async_playwright


async def check(args):
    token = json.loads(Path(args.auth_file).read_text(encoding='utf-8'))['token']
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context()
            await context.add_cookies([{
                'name': 'done_access_token', 'value': token,
                'url': 'http://localhost:3000', 'httpOnly': True, 'sameSite': 'Lax',
            }])
            await context.add_init_script('localStorage.setItem("done-token",' + json.dumps(token) + ');')
            page = await context.new_page()
            results = []
            for mode in ('cold', 'reload'):
                began = time.monotonic()
                if mode == 'cold':
                    await page.goto('http://localhost:3000/chat/' + args.project_id, wait_until='domcontentloaded')
                else:
                    await page.reload(wait_until='domcontentloaded')
                # This check targets a known non-empty room. Seeing the shell
                # or a skeleton is not successful message rendering.
                await page.locator('[data-message-id]').first.wait_for(state='visible', timeout=15000)
                results.append({'mode': mode, 'messages_visible_ms': round((time.monotonic()-began)*1000)})
            print(json.dumps(results))
            if args.output:
                Path(args.output).write_text(json.dumps(results, indent=2), encoding='utf-8')
        finally:
            await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--auth-file', required=True)
    parser.add_argument('--output')
    asyncio.run(check(parser.parse_args()))
