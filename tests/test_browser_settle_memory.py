"""open_target's 6s late-redirect wait is charged only to hosts that have not earned trust."""
import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from app.agent.v2.tools import _execute_browser_tool
from app.services import browser_recipes as memory
from tests.test_browser_plan import PageAdapter

QUIET = 'https://quiet.example.test'
BOUNCY = 'https://bouncy.example.test'


@pytest_asyncio.fixture
async def web(monkeypatch, tmp_path):
    monkeypatch.setenv('DAN_BROWSER_TIMING_LOG', str(tmp_path/'timing.jsonl'))
    monkeypatch.setenv('DAN_BROWSER_RECIPES_DIR', str(tmp_path/'recipes'))
    monkeypatch.setenv('DAN_BROWSER_OBSERVATION', 'dom')
    monkeypatch.delenv('DAN_COMMAND_JOB_ID', raising=False)
    monkeypatch.delenv('DAN_BROWSER_REPLAY', raising=False)
    monkeypatch.setattr('app.tools.browser._browser_room_id', lambda: '')
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()

        async def handle(route):
            url = route.request.url
            body = '<h1>home</h1>'
            if url.startswith(BOUNCY) and '/login' not in url:
                body = "<h1>app</h1><script>setTimeout(()=>location.href='/login',900)</script>"  # Apple-style late bounce
            await route.fulfill(content_type='text/html', body=body)
        await page.route('**/*', handle)
        proxy = PageAdapter(page)
        waits = []
        real_wait = proxy.wait_for_timeout

        async def counted(ms):
            waits.append(ms)
            return await real_wait(ms)
        proxy.wait_for_timeout = counted
        monkeypatch.setattr('app.tools.browser.get_executor_page', AsyncMock(return_value=proxy))
        try:
            yield page, waits, tmp_path/'recipes'/'settle.json'
        finally:
            await browser.close()


def test_trust_is_earned_only_by_full_waits(monkeypatch, tmp_path):
    monkeypatch.setenv('DAN_BROWSER_RECIPES_DIR', str(tmp_path))
    monkeypatch.delenv('DAN_BROWSER_REPLAY', raising=False)
    url = QUIET+'/a'
    for _ in range(2):
        memory.record_settle(url, memory.SETTLE_DEFAULT_POLLS, False)
    assert memory.settle_polls(url) == memory.SETTLE_DEFAULT_POLLS
    memory.record_settle(url, memory.SETTLE_TRUSTED_POLLS, False)   # a shortened wait proves nothing
    assert memory.settle_polls(url) == memory.SETTLE_DEFAULT_POLLS
    memory.record_settle(url, memory.SETTLE_DEFAULT_POLLS, False)
    assert memory.settle_polls(url) == memory.SETTLE_TRUSTED_POLLS
    memory.distrust(url)                                            # thrown onto a login page once
    assert memory.settle_polls(url) == memory.SETTLE_DEFAULT_POLLS
    monkeypatch.setenv('DAN_BROWSER_REPLAY', '0')
    assert memory.settle_polls(url) == memory.SETTLE_DEFAULT_POLLS


@pytest.mark.asyncio
async def test_trusted_host_opens_without_the_six_second_wait(web):
    page, waits, store = web
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({'quiet.example.test': {'full_waits': 3, 'late': 0}}), encoding='utf-8')
    await _execute_browser_tool('open_target', {'url': QUIET+'/'})
    assert waits.count(200) == memory.SETTLE_TRUSTED_POLLS - 1
    waits.clear()
    await _execute_browser_tool('open_target', {'url': 'https://unknown.example.test/'})
    assert waits.count(200) == memory.SETTLE_DEFAULT_POLLS - 1


@pytest.mark.asyncio
async def test_late_bounce_is_remembered_and_keeps_the_full_wait(web):
    page, waits, store = web
    result = await _execute_browser_tool('open_target', {'url': BOUNCY+'/'})
    assert '/login' in page.url and 'Authentication is required' in result['content'][0]['text']
    assert json.loads(store.read_text(encoding='utf-8'))['bouncy.example.test']['late'] == 1
    assert memory.settle_polls(BOUNCY+'/') == memory.SETTLE_DEFAULT_POLLS
