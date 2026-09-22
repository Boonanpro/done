"""After a robot check is solved, only the site's success callback may run. Real Chromium, no network."""
import pytest
from playwright.async_api import async_playwright

from app.tools.captcha_solver import _INJECT_RECAPTCHA_JS, _INJECT_HCAPTCHA_JS

PAGE = '''<textarea name="g-recaptcha-response"></textarea><textarea name="h-captcha-response"></textarea>
<button id="go" disabled>ログイン</button><script>
const go = document.querySelector('#go');
const widget = {S: {S: {sitekey: 'k', callback: () => { go.disabled = false; },
  'expired-callback': () => { go.disabled = true; window.expired = true; },
  'error-callback': () => { go.disabled = true; window.errored = true; }}}};
window.___grecaptcha_cfg = {clients: {0: widget}};
window.hcaptcha = {};
</script>'''


@pytest.mark.asyncio
@pytest.mark.parametrize('script', [_INJECT_RECAPTCHA_JS, _INJECT_HCAPTCHA_JS])
async def test_button_stays_enabled_after_the_check_is_solved(script):
    # Lstep (vue-recaptcha): the solver fired 'expired-callback' right after 'callback' and the login button went back to disabled.
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.set_content(PAGE)
        if script is _INJECT_HCAPTCHA_JS:
            await page.evaluate("window.hcaptchaConfig = window.___grecaptcha_cfg.clients[0]")
        result = await page.evaluate(script, 'TOKEN')
        try:
            assert not await page.evaluate('window.expired || window.errored || false')
            if script is _INJECT_RECAPTCHA_JS:
                assert result['callbacks'] == 1 and not await page.evaluate("document.querySelector('#go').disabled")
        finally:
            await browser.close()
