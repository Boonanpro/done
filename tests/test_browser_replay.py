"""Record a login once, replay it by code. Real Chromium, fictitious site, no Core."""
import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from app.agent.v2.tools import _execute_browser_tool
from app.services import browser_recipes as recipes
from tests.test_browser_plan import PageAdapter

ORIGIN = 'https://bank.example.test'
SECRET = 'correct-horse'

LOGIN = '''<h1>架空銀行 ログイン</h1>
<label>ユーザーネーム<input id="user"></label>
<label>パスワード<input id="pw" type="password" onkeydown="if(event.key==='Enter')document.querySelector('#go').click()"></label>
<button onclick="if(document.querySelector('#pw').value==='%s'){window.name=(window.name||'')+'L';location.href='/NEXT'}
  else{document.querySelector('#err').textContent='認証に失敗しました'}" id="go">LABEL</button>
<a href="/help">ヘルプ</a><p id="err"></p>'''
OTP = '''<h1>認証コードの入力</h1><label>認証コード<input id="code"></label>
<button onclick="if(document.querySelector('#code').value==='123456')location.href='/account'">認証する</button>'''
ACCOUNT = '<h1>口座</h1><a href="/statement">入出金明細</a><a href="/transfer">振込</a><button>ログアウト</button>'
TOP = '<header><a href="/entry">ログイン</a></header><h1>架空銀行</h1><footer><a href="/help">ログイン</a></footer>'
NOTICE = '<h1>重要なお知らせ</h1><p>規約が変わりました</p><button onclick="location.href=\'/account\'">同意して次へ</button>'


class Site:
    def __init__(self):
        self.label, self.next, self.popup, self.slow = 'ログイン', 'account', False, False

    async def handle(self, route):
        path = route.request.url.split(ORIGIN)[1].split('?')[0]
        body = {'/login': LOGIN.replace('%s', SECRET).replace('LABEL', self.label).replace('NEXT', self.next),
                '/otp': OTP, '/account': ACCOUNT, '/notice': NOTICE, '/top': TOP}.get(path, '<h1>404</h1>')
        if path == '/slow.png':
            import asyncio
            await asyncio.sleep(4)
            return await route.fulfill(content_type='image/png', body=b'')
        if path == '/account' and self.slow:
            body += '<img src="/slow.png">'
        if path == '/entry':  # the same form behind a URL that does not look like a login
            body = LOGIN.replace('%s', SECRET).replace('LABEL', self.label).replace('NEXT', self.next)
        if path == '/login' and self.popup == 'shadow':
            # A campaign modal in an open shadow root covering the form (KARTE-style).
            body += '''<div id="host" style="position:fixed;inset:0;background:rgba(0,0,0,.4)"></div><script>
              const root=document.querySelector('#host').attachShadow({mode:'open'});
              root.innerHTML='<p>キャンペーン</p><button id="close">閉じる</button>';
              root.querySelector('#close').onclick=()=>document.querySelector('#host').remove();</script>'''
        elif path == '/login' and self.popup:
            body += '<div id="pop"><p>キャンペーン</p><button id="close" onclick="this.parentElement.remove()">閉じる</button></div>'
        await route.fulfill(content_type='text/html; charset=utf-8', body='<meta charset="utf-8">'+body)


@pytest_asyncio.fixture
async def bank(monkeypatch, tmp_path):
    monkeypatch.setenv('DAN_BROWSER_TIMING_LOG', str(tmp_path/'timing.jsonl'))
    monkeypatch.setenv('DAN_BROWSER_RECIPES_DIR', str(tmp_path/'recipes'))
    monkeypatch.setenv('DAN_BROWSER_OBSERVATION', 'dom')
    monkeypatch.delenv('DAN_COMMAND_JOB_ID', raising=False)
    monkeypatch.delenv('DAN_BROWSER_REPLAY', raising=False)
    # These tests play the large model logging in by hand (that is what gets recorded); tests/test_browser_login.py covers the login done by code.
    monkeypatch.setenv('DAN_BROWSER_AUTOLOGIN', '0')
    monkeypatch.setattr('app.tools.browser._browser_room_id', lambda: '')
    service = AsyncMock()
    stored = {'service': 'kakuu-bank', 'id': 'owner01', 'password': SECRET, 'login_url': ORIGIN+'/login'}
    service.find_credentials_by_url.return_value = [stored]
    service.get_credential.return_value = stored
    monkeypatch.setattr('app.services.credentials_service.get_credentials_service', lambda: service)
    otp = AsyncMock()
    otp.wait_for_otp.return_value = '123456'
    monkeypatch.setattr('app.services.otp_service.get_otp_service', lambda: otp)
    site = Site()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.route(ORIGIN+'/**', site.handle)
        proxy = PageAdapter(page)
        proxy.keyboard = page.keyboard
        monkeypatch.setattr('app.tools.browser.get_executor_page', AsyncMock(return_value=proxy))
        try:
            yield page, site, tmp_path/'recipes'
        finally:
            await browser.close()


async def ref(page, selector):
    return '@'+await page.get_attribute(selector, 'data-dan-ref')


async def manual_login(page, otp=False):
    """What the large model does today, one tool call at a time."""
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    await _execute_browser_tool('fill_credential', {'ref': await ref(page, '#user'), 'field': 'username', 'url': ORIGIN+'/login'})
    await _execute_browser_tool('screenshot', {})
    await _execute_browser_tool('fill_credential', {'ref': await ref(page, '#pw'), 'url': ORIGIN+'/login'})
    await _execute_browser_tool('click', {'ref': await ref(page, '#go')})
    if otp:
        await _execute_browser_tool('wait_for_otp_from_app', {'ref': await ref(page, '#code'), 'service': 'kakuu-bank'})
        await _execute_browser_tool('click', {'ref': await ref(page, 'button')})


def saved(directory):
    return json.loads((directory/'bank.example.test.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
async def test_login_is_recorded_without_secrets_and_replayed(bank):
    page, site, directory = bank
    await manual_login(page)
    assert page.url == ORIGIN+'/account'
    # Later navigation belongs to the task, not to the login.
    await _execute_browser_tool('click', {'ref': await ref(page, 'a[href="/statement"]')})
    recipe, = saved(directory)
    assert [s['action'] for s in recipe['steps']] == ['fill_credential', 'fill_credential', 'click']
    assert SECRET not in json.dumps(recipe) and 'owner01' not in json.dumps(recipe)

    await page.evaluate("window.name=''")
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert result['replay']['replayed_login'] and result['replay']['jev_calls'] == 0
    assert page.url == ORIGIN+'/account' and await page.evaluate('window.name') == 'L'  # exactly one submit
    assert saved(directory)[0]['successes'] == 1


@pytest.mark.asyncio
async def test_otp_stays_automatic_inside_replay(bank):
    page, site, directory = bank
    site.next = 'otp'
    await manual_login(page, otp=True)
    recipe, = saved(directory)
    assert [s['action'] for s in recipe['steps']][-2:] == ['wait_for_otp_from_app', 'click']
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert result['replay']['replayed_login'] and page.url == ORIGIN+'/account'


@pytest.mark.asyncio
async def test_typed_login_id_is_stored_as_credential_step(bank):
    page, site, directory = bank
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    await _execute_browser_tool('type', {'ref': await ref(page, '#user'), 'text': 'owner01'})
    await _execute_browser_tool('fill_credential', {'ref': await ref(page, '#pw'), 'url': ORIGIN+'/login'})
    await _execute_browser_tool('click', {'ref': await ref(page, 'button')})
    recipe, = saved(directory)
    assert recipe['steps'][0]['action'] == 'fill_credential' and recipe['steps'][0]['params']['field'] == 'username'
    assert 'owner01' not in json.dumps(recipe)


@pytest.mark.asyncio
async def test_relabelled_button_is_matched_by_jev(bank, monkeypatch):
    page, site, directory = bank
    await manual_login(page)
    site.label = 'サインイン'
    asked = {}

    async def choose(self, state, questions):
        asked.update(questions)
        self.calls += 1
        answers = {}
        for key, q in questions.items():
            pick = next(k for k, v in q['criteria'].items() if 'サインイン' in v)
            answers[key] = {'type': 'choice', 'choice': pick, 'confidence': .99,
                            'probabilities': {k: (.99 if k == pick else 0) for k in q['criteria']}}
        return {'available': True, 'answers': answers}
    monkeypatch.setattr('app.services.jev_decisions.Decisions.choose', choose)
    monkeypatch.setattr('app.services.browser_replay.STEP_WAIT_SECONDS', .5)
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert result['replay']['replayed_login'] and result['replay']['jev_calls'] == 1
    assert 'ログイン' in asked['ref']['instructions'] and SECRET not in json.dumps(asked)


@pytest.mark.asyncio
async def test_notice_after_login_is_shown_to_the_model_not_clicked(bank):
    page, site, directory = bank
    await manual_login(page)
    site.next = 'notice'
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    # Which page follows a login varies by day. Logged in is verified; the notice is the model's to read.
    assert result['replay']['replayed_login'] and page.url == ORIGIN+'/notice'  # 同意ボタンは押していない
    assert '重要なお知らせ' in json.dumps(result['content'], ensure_ascii=False)


@pytest.mark.asyncio
async def test_failed_login_returns_to_the_model_and_recipe_retires(bank, monkeypatch):
    page, site, directory = bank
    await manual_login(page)
    import app.services.credentials_service as credentials
    credentials.get_credentials_service().find_credentials_by_url.return_value[0]['password'] = 'changed-elsewhere'
    monkeypatch.setattr('app.services.browser_replay.END_WAIT_SECONDS', .5)
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert result['replay']['needs_agent'] and result['replay']['reason'] == 'destination_not_verified'
    assert 'ALREADY executed' in result['content'][0]['text']
    # Two failures retire the recipe: no third automatic attempt against the account.
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert saved(directory)[0]['enabled'] is False
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert 'replay' not in result and page.url == ORIGIN+'/login'


@pytest.mark.asyncio
async def test_popup_step_is_skipped_when_popup_is_absent(bank):
    page, site, directory = bank
    site.popup = True
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    await _execute_browser_tool('click', {'ref': await ref(page, '#close')})
    await _execute_browser_tool('fill_credential', {'ref': await ref(page, '#user'), 'field': 'username', 'url': ORIGIN+'/login'})
    await _execute_browser_tool('fill_credential', {'ref': await ref(page, '#pw'), 'url': ORIGIN+'/login'})
    await _execute_browser_tool('click', {'ref': await ref(page, '#go')})
    assert len(saved(directory)[0]['steps']) == 4
    site.popup = False
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert result['replay']['replayed_login'] and result['replay']['skipped_steps'] == 1


@pytest.mark.asyncio
async def test_wrong_password_is_not_a_recipe_and_kill_switch(bank, monkeypatch):
    page, site, directory = bank
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    await _execute_browser_tool('fill_credential', {'ref': await ref(page, '#user'), 'field': 'username', 'url': ORIGIN+'/login'})
    await _execute_browser_tool('click', {'ref': await ref(page, 'button')})
    assert not (directory/'bank.example.test.json').exists()
    await manual_login(page)
    monkeypatch.setenv('DAN_BROWSER_REPLAY', '0')
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert 'replay' not in result and page.url == ORIGIN+'/login'


@pytest.mark.asyncio
async def test_shadow_dom_popup_is_visible_clickable_and_replayed(bank):
    page, site, directory = bank
    site.popup = 'shadow'
    seen = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    listing = json.dumps(seen['content'], ensure_ascii=False)
    assert '閉じる' in listing  # used to be invisible: coordinates were the only way
    close = '@'+await page.evaluate("document.querySelector('#host').shadowRoot.querySelector('#close').getAttribute('data-dan-ref')")
    blocked = await _execute_browser_tool('click', {'ref': await ref(page, '#go')})
    assert blocked['success'] is False and blocked['reason'] == 'occluded'
    await _execute_browser_tool('click', {'ref': close})
    assert await page.evaluate("!document.querySelector('#host')")
    await _execute_browser_tool('fill_credential', {'ref': await ref(page, '#user'), 'field': 'username', 'url': ORIGIN+'/login'})
    await _execute_browser_tool('fill_credential', {'ref': await ref(page, '#pw'), 'url': ORIGIN+'/login'})
    await _execute_browser_tool('click', {'ref': await ref(page, '#go')})
    assert saved(directory)[0]['steps'][0]['targets']['ref']['name'] == '閉じる'
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert result['replay']['replayed_login'] and page.url == ORIGIN+'/account'


@pytest.mark.asyncio
async def test_login_started_from_the_top_page_with_twin_links(bank):
    page, site, directory = bank
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/top'})
    await _execute_browser_tool('click', {'ref': await ref(page, 'header a')})
    await _execute_browser_tool('fill_credential', {'ref': await ref(page, '#user'), 'field': 'username', 'url': ORIGIN+'/entry'})
    await _execute_browser_tool('fill_credential', {'ref': await ref(page, '#pw'), 'url': ORIGIN+'/entry'})
    await _execute_browser_tool('click', {'ref': await ref(page, '#go')})
    first = saved(directory)[0]['steps'][0]
    assert first['targets']['ref']['nth'] == 0 and first['targets']['ref']['of'] == 2
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/top'})
    assert result['replay']['replayed_login'] and page.url == ORIGIN+'/account'  # header link, not the footer twin


@pytest.mark.asyncio
async def test_arriving_at_a_known_login_page_by_click_also_replays(bank):
    page, site, directory = bank
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/entry'})  # learn the login page itself
    await _execute_browser_tool('fill_credential', {'ref': await ref(page, '#user'), 'field': 'username', 'url': ORIGIN+'/entry'})
    await _execute_browser_tool('fill_credential', {'ref': await ref(page, '#pw'), 'url': ORIGIN+'/entry'})
    await _execute_browser_tool('click', {'ref': await ref(page, '#go')})
    assert saved(directory)[0]['landing'] == 'bank.example.test/entry'
    # Another day Dan starts from the top page and clicks the link: same login page, reached by click.
    await page.goto(ORIGIN+'/top')
    await _execute_browser_tool('screenshot', {})
    result = await _execute_browser_tool('click', {'ref': await ref(page, 'header a')})
    assert result['replay']['replayed_login'] and page.url == ORIGIN+'/account'


@pytest.mark.asyncio
async def test_click_that_stays_on_the_login_page_is_not_hijacked(bank):
    page, site, directory = bank
    await manual_login(page)
    await page.goto(ORIGIN+'/login')
    await _execute_browser_tool('screenshot', {})
    result = await _execute_browser_tool('click', {'ref': await ref(page, '#user')})
    assert 'replay' not in result and page.url == ORIGIN+'/login'


@pytest.mark.asyncio
async def test_unreadable_page_during_navigation_does_not_abort_the_login(bank, monkeypatch):
    page, site, directory = bank
    await manual_login(page)
    from app.services import browser_recipes
    real, calls = browser_recipes.snapshot, {'n': 0}

    async def flaky(p):
        calls['n'] += 1
        if calls['n'] in (3, 4):  # right after the submit, as on the real bank
            raise RuntimeError('Page.evaluate: Execution context was destroyed, most likely because of a navigation.')
        return await real(p)
    monkeypatch.setattr(browser_recipes, 'snapshot', flaky)
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert calls['n'] > 4 and result['replay']['replayed_login'] and page.url == ORIGIN+'/account'


@pytest.mark.asyncio
async def test_remembered_entrance_is_told_instead_of_guessed(bank):
    page, site, directory = bank
    assert recipes.entry_hint(ORIGIN+'/anything') is None
    await manual_login(page)
    # Looking up credentials, or opening a stale URL from old notes, both point at the entrance that works.
    from app.agent.v2.tools import _remembered_login_note
    assert ORIGIN+'/login' in _remembered_login_note(None, 'bank.example.test')
    await page.evaluate("window.name=''")
    dead = await _execute_browser_tool('open_target', {'url': ORIGIN+'/old-login-page-from-notes'})
    assert 'replay' not in dead and ORIGIN+'/login' in dead['content'][-1]['text']
    opened = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert opened['replay']['replayed_login'] and '記憶済み' not in json.dumps(opened['content'], ensure_ascii=False)


def test_enter_waits_for_full_load_only_outside_a_replay():
    """A replay verifies 'left the login page' itself; the full load event (3.7-6.2s on the real bank) adds nothing."""
    from app.agent.v2.tools import _enter_wait_state
    assert _enter_wait_state() == 'load'
    token = recipes.replaying.set(True)
    try:
        assert _enter_wait_state() == 'domcontentloaded'
    finally:
        recipes.replaying.reset(token)
    assert _enter_wait_state() == 'load'


@pytest.mark.asyncio
async def test_login_submitted_with_enter_is_replayed(bank):
    page, site, directory = bank
    site.slow = True
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    await _execute_browser_tool('fill_credential', {'ref': await ref(page, '#user'), 'field': 'username', 'url': ORIGIN+'/login'})
    await _execute_browser_tool('fill_credential', {'ref': await ref(page, '#pw'), 'url': ORIGIN+'/login', 'press_enter': True})
    await _execute_browser_tool('screenshot', {})
    assert saved(directory)[0]['steps'][-1]['params'].get('press_enter') is True
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert result['replay']['replayed_login'] and page.url == ORIGIN+'/account'
