"""First login on a site without the model walking the form. Real Chromium, fictitious site, no Core."""
import json

import pytest

from app.agent.v2.tools import _execute_browser_tool
from tests.test_browser_replay import bank as manual_bank, ref, saved, ORIGIN, SECRET  # noqa: F401  (fixture)


@pytest.fixture
def bank(manual_bank, monkeypatch):
    monkeypatch.delenv('DAN_BROWSER_AUTOLOGIN', raising=False)
    return manual_bank


@pytest.mark.asyncio
async def test_first_login_is_done_by_code_and_remembered(bank):
    page, site, directory = bank
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert result['login']['logged_in'] and result['login']['completed_steps'][:2] == ['id', 'password']
    assert page.url == ORIGIN+'/account' and await page.evaluate('window.name') == 'L'   # exactly one submit
    text = json.dumps(result, ensure_ascii=False)
    assert SECRET not in text and 'owner01' not in text
    # what code did is recorded like a model's login, even when the login is the last thing done: the next visit is a replay
    recipe, = saved(directory)
    assert [s['action'] for s in recipe['steps']] == ['fill_credential', 'fill_credential', 'click']
    await page.evaluate("window.name=''")
    again = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert again['replay']['replayed_login'] and 'login' not in again


@pytest.mark.asyncio
async def test_one_time_code_is_part_of_the_same_login(bank):
    page, site, _ = bank
    site.next = 'otp'
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert result['login']['logged_in'] and page.url == ORIGIN+'/account'
    assert any(step.startswith('code by') for step in result['login']['completed_steps'])


@pytest.mark.asyncio
async def test_rejected_password_is_never_submitted_twice(bank, monkeypatch):
    page, site, directory = bank
    from app.services.credentials_service import get_credentials_service
    get_credentials_service().find_credentials_by_url.return_value = [{'service': 'kakuu-bank', 'id': 'owner01', 'password': 'wrong', 'login_url': ORIGIN+'/login'}]
    get_credentials_service().get_credential.return_value = {'service': 'kakuu-bank', 'id': 'owner01', 'password': 'wrong'}
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert result['login']['reason'] == 'login_rejected' and '認証に失敗' in result['login']['site_message']
    assert result['login']['site_message'] == '認証に失敗しました'   # the site's own new line, not a keyword window
    assert result['login']['elapsed_ms'] < 6000   # the site's reply ends the wait; no fixed ten seconds
    assert await page.evaluate('window.name') in ('', None) and page.url == ORIGIN+'/login'
    assert not (directory/'bank.example.test.json').exists()


@pytest.mark.asyncio
async def test_no_saved_account_means_no_typing_and_the_model_is_told(bank):
    page, site, _ = bank
    from app.services.credentials_service import get_credentials_service
    get_credentials_service().find_credentials_by_url.return_value = []
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert 'login' not in result and '保存されていません' in json.dumps(result, ensure_ascii=False)
    assert await page.input_value('#pw') == ''


@pytest.mark.asyncio
async def test_kill_switch_and_pages_that_are_not_a_login(bank, monkeypatch):
    page, site, _ = bank
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/top'})
    assert 'login' not in result
    monkeypatch.setenv('DAN_BROWSER_AUTOLOGIN', '0')
    result = await _execute_browser_tool('open_target', {'url': ORIGIN+'/login'})
    assert 'login' not in result and page.url == ORIGIN+'/login'
