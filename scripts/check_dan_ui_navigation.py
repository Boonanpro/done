"""Read-only UI checks against a separately launched frontend and editor page.

Uses the existing local session token without printing it. No messages, media
generation, project mutations or voice connections are initiated.
"""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright, expect


async def run(frontend: str, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    token = (Path.home() / '.done/native_token.txt').read_text().strip()
    result = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel='msedge', headless=True)
        context = await browser.new_context(viewport={'width': 1440, 'height': 900})
        # Existing credentials remain only in memory and the ephemeral browser.
        await context.add_init_script('localStorage.setItem("done-token", ' + json.dumps(token) + ');')
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(frontend + '/chat', wait_until='domcontentloaded', timeout=120000)
        separator = page.get_by_role('separator', name='メニューの幅')
        await expect(separator).to_be_visible(timeout=60000)
        await separator.focus()
        initial = int(await separator.get_attribute('aria-valuenow'))
        await page.keyboard.press('ArrowRight')
        await expect(separator).to_have_attribute('aria-valuenow', str(initial + 16))
        await page.keyboard.press('Home')
        await expect(separator).to_have_attribute('aria-valuenow', '220')
        await page.keyboard.press('End')
        await expect(separator).to_have_attribute('aria-valuenow', '480')
        await separator.dblclick()
        await expect(separator).to_have_attribute('aria-valuenow', '280')
        bounds = await separator.bounding_box()
        x, y = bounds['x'] + bounds['width'] / 2, 350
        await page.mouse.move(x, y)
        await page.mouse.down()
        await page.mouse.move(x + 40, y)
        await page.mouse.up()
        await expect(separator).to_have_attribute('aria-valuenow', '320')
        await page.screenshot(path=str(output / 'desktop.png'))
        result['desktop_resize_keyboard_pointer'] = True

        # Seed only this ephemeral tab's preview UI state; no artifact is edited.
        await page.evaluate('localStorage.setItem("dan-preview-state", JSON.stringify({version:3,state:{isOpen:true}}))')
        await page.reload(wait_until='domcontentloaded')
        trigger = page.get_by_role('button', name='メニューを開く', exact=True)
        await expect(trigger).to_be_visible(timeout=30000)
        await trigger.focus()
        await page.keyboard.press('Enter')
        dialog = page.get_by_role('dialog', name='ダンのメニュー')
        await expect(dialog).to_be_visible()
        await page.keyboard.press('Shift+Tab')
        assert await dialog.evaluate('(node)=>node.contains(document.activeElement)')
        # Close the focused footer tooltip before exercising the drawer's Escape.
        await dialog.get_by_role('button', name='閉じる', exact=True).focus()
        await expect(page.get_by_role('tooltip')).to_have_count(0)
        await page.screenshot(path=str(output / 'preview-menu.png'))
        await page.keyboard.press('Escape')
        await expect(dialog).not_to_be_visible()
        await expect(trigger).to_be_focused()
        result['preview_menu_keyboard_focus_return'] = True

        await page.set_viewport_size({'width': 390, 'height': 844})
        # The existing initial mobile experience opens navigation for an empty chat.
        await expect(dialog).to_be_visible()
        await page.screenshot(path=str(output / 'mobile-web-menu.png'))
        await dialog.get_by_role('button', name='閉じる', exact=True).click()
        await expect(trigger).to_be_focused()
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        result['mobile_web_menu_no_overflow'] = True

        editor = await context.new_page()
        editor.on('pageerror', lambda error: errors.append(str(error)))
        # Serve the real editor sources without connecting any production session.
        static = Path(__file__).resolve().parents[1] / 'app/static'
        sources = {
            'page': ('text/html', ['editor-assistant.html']),
            'script': ('text/javascript', ['editor-assistant.js']),
            'live-script': ('text/javascript', ['editor-live.js']),
            'proposal-script': ('text/javascript', ['editor-scene.js', 'editor-proposals.js']),
            'proposal-style': ('text/css', ['editor-proposals.css']),
        }
        async def editor_source(route):
            name = route.request.url.split('?')[0].rsplit('/', 1)[-1]
            if name in sources:
                content_type, files = sources[name]
                await route.fulfill(content_type=content_type, body='\n'.join((static / file).read_text(encoding='utf-8-sig') for file in files))
            else:
                await route.abort()
        await editor.route('**/api/v1/editor-assistant/**', editor_source)
        await editor.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page', wait_until='networkidle')
        await expect(editor.locator('#attach')).to_have_attribute('data-label', '素材')
        await editor.locator('#show-chat').click()
        await expect(editor.locator('#input')).to_be_focused()
        await expect(editor.locator('#consultation-inspector')).not_to_be_visible()
        await expect(editor.locator('#show-chat')).to_have_attribute('aria-expanded', 'true')
        await editor.locator('#input').fill('検証用の未送信下書き')
        await editor.keyboard.press('Escape')
        await expect(editor.locator('#show-chat')).to_be_focused()
        await expect(editor.locator('#show-chat')).to_have_attribute('aria-expanded', 'false')
        await editor.locator('#show-chat').click()
        await expect(editor.locator('#input')).to_have_value('検証用の未送信下書き')
        await editor.screenshot(path=str(output / 'editor-desktop.png'))
        await editor.locator('#show-consultation').click()
        await expect(editor.locator('#consultation-inspector')).to_be_visible()
        await expect(editor.locator('#drawer')).not_to_be_visible()
        await editor.locator('#show-chat').click()
        await expect(editor.locator('#consultation-inspector')).not_to_be_visible()
        await expect(editor.locator('#input')).to_have_value('検証用の未送信下書き')
        # Verify presentation follows transport-owned labels without starting audio.
        for label, visible in [('マイクを止める', 'ミュート'), ('マイクをオン', '再開'), ('マイクで話す', '話す')]:
            await editor.locator('#mic').evaluate('(node,label)=>node.setAttribute("aria-label",label)', label)
            await expect(editor.locator('#mic')).to_have_attribute('data-label', visible)
        result['editor_drawer_draft_focus_and_mic_label'] = True
        await editor.locator('#hide-chat').click()
        await editor.set_viewport_size({'width': 390, 'height': 844})
        await editor.screenshot(path=str(output / 'editor-narrow.png'))
        for width in [320, 390, 700]:
            await editor.set_viewport_size({'width': width, 'height': 844})
            boxes = [await editor.locator('#' + name).bounding_box() for name in ['attach', 'show-chat', 'mic', 'disconnect']]
            assert all(box['width'] >= 48 and box['height'] >= 48 and box['x'] >= 0 and box['x'] + box['width'] <= width for box in boxes)
            assert all(a['x'] + a['width'] <= b['x'] for a, b in zip(boxes, boxes[1:]))
        result['editor_toolbar_320_390_700'] = True
        result['editor_source_mode'] = 'real source files, isolated transport; no voice or backend mutations'
        result['page_errors'] = errors
        assert not errors, errors
        (output / 'browser-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
        await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--frontend', default='http://127.0.0.1:3014')
    parser.add_argument('--output', type=Path, default=Path('scratch/dan-ui-implementation-20260923'))
    args = parser.parse_args()
    asyncio.run(run(args.frontend, args.output))
