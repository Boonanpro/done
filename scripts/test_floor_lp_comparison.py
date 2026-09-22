"""Same-content visual comparison and interactive editing acceptance (local only)."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'scratch/floor-lp-comparison'
URL = 'http://localhost:3001/preview/floor-lp-compare'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1500, 'height': 1050})
        context.route('**/api/**', lambda r: r.fulfill(json=[]))
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(URL, wait_until='domcontentloaded', timeout=60000)
        print('page loaded', flush=True)
        page.evaluate('document.fonts.ready')
        expect(page.get_by_role('status')).not_to_have_text('保存した編集を読み込み中…')
        expect(page.locator('.floor-lp h1')).to_contain_text('コンセントで')
        page.wait_for_function('Array.from(document.images).every(e => e.complete && e.naturalWidth > 0)')
        page.screenshot(path=str(OUT/'comparison.png'), full_page=True)
        page.locator('.floor-lab-original').screenshot(path=str(OUT/'original.png'))
        page.locator('.floor-lab-result').screenshot(path=str(OUT/'editable.png'))
        measurements = page.evaluate('''() => Object.fromEntries([
          ['original', '.floor-lab-original'], ['reconstruction', '.floor-lp'],
          ['hero', '.floor-hero'], ['heading', '.floor-hero-heading'],
          ['heroPhoto', '.floor-hero-photo'], ['problemHeading', '.floor-problem-heading']
        ].map(([name, selector]) => { const r = document.querySelector(selector).getBoundingClientRect(); return [name,{width:r.width,height:r.height}]; }))''')
        title = page.locator('[data-edit-id="floor-hero-title"]')
        title.click()
        editor = page.get_by_role('textbox', name='選択したテキスト')
        expect(editor).to_be_visible()
        editor.fill('足元から、\n暮らしをあたたかく。')
        expect(title).to_have_text('足元から、暮らしをあたたかく。')
        page.get_by_role('button', name='元に戻す', exact=True).click()
        expect(title).to_have_text('コンセントで使える床暖房。')
        title.click()
        editor.fill('足元から、\n暮らしをあたたかく。')
        page.get_by_role('checkbox', name='写真を隠す').check()
        expect(page.locator('.floor-hero-photo')).to_have_css('visibility','hidden')
        expect(title).to_be_visible()
        expect(page.locator('table')).to_be_visible()
        page.locator('.floor-lab-result').screenshot(path=str(OUT/'native-only.png'))
        page.reload(wait_until='domcontentloaded')
        expect(page.locator('[data-edit-id="floor-hero-title"]')).to_have_text('足元から、暮らしをあたたかく。')
        page.get_by_role('button', name='初期状態に戻す').click()
        expect(title).to_have_text('コンセントで使える床暖房。')
        page.get_by_role('button', name='編集版だけ', exact=True).click()
        page.set_viewport_size({'width':390,'height':844})
        page.locator('.floor-lab-result').screenshot(path=str(OUT/'mobile.png'))
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        ids = page.locator('.floor-lp [data-edit-id]').evaluate_all('(els)=>els.map(e=>e.dataset.editId)')
        assert len(ids)==len(set(ids))
        assert not errors, errors
        report={'checks':['Same-content source/reconstruction displayed side by side','All photos loaded','Heading edited through visible UI','Native text and table remain with all photographs hidden','Changes restored after page reload','Reset restores original content','Mobile has no horizontal overflow','All editing IDs unique; no browser errors'], 'measurements':measurements,'editableElements':len(ids)}
        (OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))
        browser.close()


if __name__=='__main__': main()
