"""Browser acceptance for the editable LP. API storage is isolated in memory;
release SSR is checked using the actual Next page and a temporary local release.
No publication, customer content, or production database writes are performed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]



def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--origin', default='http://localhost:3001')
    parser.add_argument('--output', default='scratch/editable-lp-verification')
    parser.add_argument('--floor', action='store_true', help='Verify the accepted floor LP through the ordinary inspector')
    args = parser.parse_args()
    slug = 'floor-lp-native' if args.floor else 'editable-lp-lab'
    title_id = 'floor-hero-title' if args.floor else 'elp-top-title'
    photo_id = 'floor-hero-photo' if args.floor else 'elp-top-photo'
    hero_id = 'floor-hero-section' if args.floor else 'elp-top-hero'
    release_path = ROOT / f'frontend/src/app/artifacts/{slug}/release.gen.json'
    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)
    rows: dict = {}
    publications: list[dict] = []
    checks: list[str] = []
    original = release_path.read_bytes()

    def api(route):
        request = route.request
        if '/inspector-overrides' in request.url:
            if request.method == 'POST' and request.url.split('?')[0].endswith('inspector-overrides'):
                data = request.post_data_json
                assert data['artifact_slug'] == slug
                rows[data['element_key']] = {
                    'element_key': data['element_key'], 'styles': data.get('styles'), 'attrs': data.get('attrs'),
                }
                route.fulfill(json=rows[data['element_key']])
            elif request.method == 'GET':
                route.fulfill(json=list(rows.values()))
            elif request.method == 'POST' and '/publish?' in request.url:
                release = {key: {'attrs': row['attrs'], 'styles': row['styles']} for key, row in rows.items()}
                release_path.write_text(json.dumps(release, ensure_ascii=False), encoding='utf-8')
                publications.append(release)
                route.fulfill(json={'revision': len(publications)})
            else:
                route.fulfill(status=409, json={'detail': 'Publication is disabled in this test'})
        else:
            route.fulfill(json=[])

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.route('**/api/**', api)
            page = context.new_page()
            page.goto(f'{args.origin}/preview/{slug}', wait_until='networkidle')
            expect(page.locator('h1')).to_contain_text('コンセントで' if args.floor else '砂かきの時間を、')
            page.screenshot(path=str(out / 'desktop.png'), full_page=True)
            ids = page.locator('[data-edit-id]').evaluate_all('(els) => els.map(e => e.dataset.editId)')
            assert len(ids) == len(set(ids)) and len(ids) >= (20 if args.floor else 30)
            assert page.locator('img').evaluate_all('(els) => els.every(e => e.complete && e.naturalWidth > 0)')
            checks.append('Native LP renders with unique editable IDs and loaded photographs')
            for width in [390, 700, 1024]:
                page.set_viewport_size({'width': width, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'overflow at {width}'
                if width == 390:
                    page.screenshot(path=str(out / 'mobile.png'), full_page=True)
            checks.append('No horizontal overflow at 390, 700, 1024px')
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.goto(f'{args.origin}/test-inspector?slug={slug}', wait_until='networkidle')
            frame = page.frame_locator('iframe').first
            title = frame.locator(f'[data-edit-id="{title_id}"]')
            expect(title).to_be_visible(timeout=60000)
            title.click()
            editor = page.get_by_role('textbox', name='テキストを編集')
            expect(editor).to_be_visible()
            line_height = page.get_by_role('spinbutton', name='行間（数値）')
            assert abs(float(line_height.input_value()) - (1.32 if args.floor else 1.4)) < 0.02
            line_height.fill('1.8')
            page.wait_for_function("""(id) => {
              const e = document.querySelector('iframe').contentDocument.querySelector(`[data-edit-id="${id}"]`);
              const s = getComputedStyle(e); return Math.abs(parseFloat(s.lineHeight)/parseFloat(s.fontSize)-1.8) < .02;
            }""", arg=title_id)
            text = ('工事なしで、足元から。\n毎日の暮らしをもっと暖かく。' if args.floor
                    else '猫との時間を、もっと。\n毎日のお手入れを気持ちよく。')
            editor.fill(text)
            expect(title).to_have_text(text.replace('\n', ''))
            checks.append('Actual inspector edits multiline heading and preserves unitless line height')
            page.wait_for_timeout(1500)
            assert f'@{title_id}' in rows
            photo = frame.locator(f'[data-edit-id="{photo_id}"]')
            photo.click()
            page.get_by_role('textbox', name='画像のURL').fill('/editable-lp-example/stainless.webp')
            page.get_by_role('button', name='この画像に差し替える').click()
            expect(photo).to_have_attribute('src', '/editable-lp-example/stainless.webp')
            page.evaluate("(key) => window.usePreviewStore.getState().applyStyleTo(key, 'padding-top', '24px')", '@' + hero_id)
            page.wait_for_timeout(1500)
            assert f'@{photo_id}' in rows and f'@{hero_id}' in rows
            page.screenshot(path=str(out / 'editor.png'), full_page=True)
            # Fresh browser storage proves reload uses saved API rows, not localStorage.
            fresh = browser.new_context(viewport={'width': 1440, 'height': 1000})
            fresh.route('**/api/**', api)
            reloaded = fresh.new_page()
            reloaded.goto(f'{args.origin}/test-inspector?slug={slug}', wait_until='networkidle')
            fresh_frame = reloaded.frame_locator('iframe').first
            expect(fresh_frame.locator(f'[data-edit-id="{title_id}"]')).to_have_text(text.replace('\n', ''), timeout=30000)
            expect(fresh_frame.locator(f'[data-edit-id="{photo_id}"]')).to_have_attribute('src', '/editable-lp-example/stainless.webp')
            expect(fresh_frame.locator(f'[data-edit-id="{hero_id}"]')).to_have_css('padding-top', '24px')
            checks.append('Image replaced through inspector UI; text, media, and layout survive fresh API reload')
            page.get_by_role('button', name='保存', exact=True).click()
            expect(page.get_by_text('保存しました', exact=True)).to_be_visible()
            assert len(publications) == 1 and publications[0]
            checks.append('Ordinary Save button flushes drafts and requests a release (isolated API fixture)')
            # JS disabled: only the actual server-rendered release can pass these checks.
            ssr = browser.new_context(java_script_enabled=False, viewport={'width': 1440, 'height': 1000})
            ssr.route('**/api/**', api)
            published = ssr.new_page()
            published.goto(f'{args.origin}/preview/{slug}', wait_until='networkidle')
            expect(published.locator(f'[data-edit-id="{title_id}"]')).to_have_text(text.replace('\n', ''))
            expect(published.locator(f'[data-edit-id="{photo_id}"]')).to_have_attribute('src', '/editable-lp-example/stainless.webp')
            expect(published.locator(f'[data-edit-id="{hero_id}"]')).to_have_css('padding-top', '24px')
            checks.append('Actual release SSR includes text, replaced photo, and section padding with JS disabled')
            published.set_viewport_size({'width': 390, 'height': 844})
            hero_box = published.locator(f'[data-edit-id="{hero_id}"]').bounding_box()
            details_box = published.locator('[data-edit-id="floor-problem-section"]' if args.floor else '#details').bounding_box()
            title_box = published.locator(f'[data-edit-id="{title_id}"]').bounding_box()
            assert hero_box and details_box and title_box
            assert title_box['x'] >= 0 and title_box['x'] + title_box['width'] <= 390
            assert details_box['y'] >= hero_box['y'] + hero_box['height'] - 1
            published.screenshot(path=str(out / 'mobile-edited.png'), full_page=True)
            checks.append('Longer edited mobile heading remains in flow without overlapping the next section')
            browser.close()
    finally:
        release_path.write_bytes(original)
    report = {'checks': checks, 'storage': 'in-memory API fixture; production DB/deploy not tested'}
    (out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
