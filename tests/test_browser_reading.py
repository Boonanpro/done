"""read / find / click(label): the fixed forms of what Dan used to hand-write in evaluate."""
import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from app.agent.v2.tools import _execute_browser_tool
from tests.test_browser_plan import PageAdapter

PAGE = '''<meta charset="utf-8"><title>入出金明細</title>
<nav><a href="#home">ホーム</a><a href="#transfer">振込</a></nav>
<main><h1>入出金明細</h1><p id="lead">''' + 'あ'*300 + '''</p>
<table><tr><th>日付</th><th>内容</th><th>金額</th></tr>
<tr><td>9/19</td><td>振込 カ）サンプル</td><td>-465</td></tr><tr><td>9/20</td><td>利息</td><td>12</td></tr></table>
<p>2025年4月の明細はここから。<span id="deep">重要な一文</span></p>
<a href="#next" onclick="document.title='next clicked'"><span>次へ</span></a>
<a href="#d1" onclick="document.title='wrong'">詳細</a><a href="#d2" onclick="document.title='wrong'">詳細</a>
<div id="plain" onclick="document.title='div clicked'">同意して確認完了</div>
<style>.cb{position:relative;display:inline-block}.cb input{position:absolute;left:0;top:4px;width:13px;height:13px;margin:0}
.cb label{position:relative;display:inline-block;padding-left:24px;background:#fff}</style>
<span class="cb"><input type="checkbox" id="agree"><label for="agree">確認しました</label></span>
<div id="host"></div></main>
<script>const r=document.querySelector('#host').attachShadow({mode:'open'});
r.innerHTML='<button id="inner">影の中のボタン</button>';r.querySelector('#inner').onclick=()=>{document.title='shadow clicked'};</script>'''


@pytest_asyncio.fixture
async def site(monkeypatch, tmp_path):
    monkeypatch.setenv('DAN_BROWSER_TIMING_LOG', str(tmp_path/'timing.jsonl'))
    monkeypatch.setenv('DAN_BROWSER_RECIPES_DIR', str(tmp_path/'recipes'))
    monkeypatch.delenv('DAN_COMMAND_JOB_ID', raising=False)
    monkeypatch.setattr('app.tools.browser._browser_room_id', lambda: '')
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.route('https://bank.example.test/**', lambda route: route.fulfill(content_type='text/html; charset=utf-8', body=PAGE))
        monkeypatch.setattr('app.tools.browser.get_executor_page', AsyncMock(return_value=PageAdapter(page)))
        await _execute_browser_tool('open', {'url': 'https://bank.example.test/statement', 'observation': 'dom'})
        try:
            yield page
        finally:
            await browser.close()


def text_of(result):
    return '\n'.join(b['text'] for b in result['content'] if b['type'] == 'text')


@pytest.mark.asyncio
async def test_observation_with_image_also_carries_the_page_text(site):
    result = await _execute_browser_tool('screenshot', {})
    assert any(b['type'] == 'image' for b in result['content'])
    text = text_of(result)
    assert '画面の本文' in text and '振込 カ）サンプル' in text
    assert 'ホーム' not in text.split('ページ状態:')[0].split('画面の本文')[1]  # main content, not the nav


@pytest.mark.asyncio
async def test_read_range_tables_and_paging(site):
    result = await _execute_browser_tool('read', {'after': '2025年4月', 'max_chars': 100})
    body = text_of(result).split('本文:\n')[1]
    assert body.startswith('2025年4月の明細はここから') and '重要な一文' in body
    tables = text_of(await _execute_browser_tool('read', {'tables': True, 'selector': 'main'}))
    assert '9/19 | 振込 カ）サンプル | -465' in tables and '表1（全3行）' in tables
    first = text_of(await _execute_browser_tool('read', {'max_chars': 100}))
    assert 'offset=100' in first
    missing = await _execute_browser_tool('read', {'selector': '#nope'})
    assert missing['success'] is False


@pytest.mark.asyncio
async def test_find_returns_usable_refs_including_shadow_and_plain_text(site):
    result = await _execute_browser_tool('find', {'query': '影の中'})
    assert result['count'] == 1 and result['results'][0]['clickable']
    await _execute_browser_tool('click', {'ref': result['results'][0]['ref'], 'observation': 'dom'})
    assert await site.title() == 'shadow clicked'
    plain = await _execute_browser_tool('find', {'query': '重要な一文'})
    assert plain['results'][0]['clickable'] is False and '2025年4月' in plain['results'][0]['context']
    both = await _execute_browser_tool('find', {'query': '^(次へ|詳細)$', 'regex': True})
    assert [r['text'] for r in both['results']] == ['次へ', '詳細', '詳細'] and all(r['tag'] == 'a' for r in both['results'])
    assert (await _execute_browser_tool('find', {'query': ''}))['success'] is False


@pytest.mark.asyncio
async def test_click_by_label_clicks_only_a_unique_target(site):
    await _execute_browser_tool('click', {'label': '次へ', 'observation': 'dom'})
    assert await site.title() == 'next clicked'
    await _execute_browser_tool('click', {'label': '同意して確認完了', 'observation': 'dom'})  # a div with onclick
    assert await site.title() == 'div clicked'
    ambiguous = await _execute_browser_tool('click', {'label': '詳細'})
    assert ambiguous['success'] is False and ambiguous['dispatched'] is False and len(ambiguous['candidates']) == 2
    assert await site.title() == 'div clicked'
    missing = await _execute_browser_tool('click', {'label': '存在しないボタン'})
    assert missing['reason'] == 'label_not_found' and await site.title() == 'div clicked'


@pytest.mark.asyncio
async def test_click_by_label_under_a_command_job_only_resolves(site, monkeypatch):
    monkeypatch.setenv('DAN_COMMAND_JOB_ID', 'job-1')
    result = await _execute_browser_tool('click', {'label': '次へ'})
    assert result['reason'] == 'use_ref' and result['ref'].startswith('@') and await site.title() == '入出金明細'


@pytest.mark.asyncio
async def test_checkbox_hidden_under_its_own_label_is_clicked_through_the_label(site):
    await _execute_browser_tool('screenshot', {})
    ref = '@'+await site.get_attribute('#agree', 'data-dan-ref')
    result = await _execute_browser_tool('click', {'ref': ref, 'observation': 'dom'})
    assert result.get('success') is not False and await site.is_checked('#agree')
