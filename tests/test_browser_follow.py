"""follow: several labelled presses in one tool call. Real Chromium, fictitious site, Jev replaced by a stand-in."""
import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from app.agent.v2.tools import _execute_browser_tool
from tests.test_browser_plan import PageAdapter

ORIGIN = 'https://bank.example.test'
PAGES = {
    '/home': '<title>ホーム</title><nav><a href="/accounts">口座情報・入出金</a><a href="/transfer">振込</a><a href="/help">お問い合わせ</a></nav><main><h1>ホーム</h1></main>',
    '/accounts': '<title>口座情報</title><main><h1>口座情報</h1><a href="/statement">入出金明細</a><a href="/balance">残高照会</a></main>',
    '/statement': '''<title>入出金明細</title><main><h1>入出金明細</h1><p id="range">今月</p>
        <button onclick="document.querySelector('#range').textContent='9月の明細を表示中'">絞り込み</button>
        <button onclick="document.title='SENT'">送信</button><button>何も起きないボタン</button>
        <ul><li>A社 <a href="/detail/a">詳細</a></li><li>B社 <a href="/detail/b">詳細</a></li></ul></main>''',
    '/detail/b': '<title>B社の詳細</title><main><h1>B社</h1></main>',
    '/secure': '<title>ログイン</title><main><label>パスワード<input type="password"></label><a href="/home">戻る</a></main>',
}


class FakeJev:
    """Picks the candidate containing a keyword; confidence is set by the test."""
    def __init__(self):
        self.calls, self.rules, self.confidence, self.asked = 0, [], .99, []

    async def choose(self, state, questions):
        self.calls += 1
        q = questions['next']; self.asked.append((state, q))
        pick = 'none'
        for needle, wanted in self.rules:
            if needle in json.dumps(state, ensure_ascii=False)+q['instructions']:
                pick = next((k for k, v in q['criteria'].items() if wanted in v), 'none')
                if pick != 'none':
                    break
        probs = {k: 0.0 for k in q['criteria']}
        probs[pick] = self.confidence
        rest = next(k for k in probs if k != pick); probs[rest] = round(1-self.confidence, 6)
        return {'available': True, 'answers': {'next': {'type': 'choice', 'choice': pick, 'confidence': self.confidence, 'probabilities': probs}}}


@pytest_asyncio.fixture
async def site(monkeypatch, tmp_path):
    monkeypatch.setenv('DAN_BROWSER_TIMING_LOG', str(tmp_path/'timing.jsonl'))
    monkeypatch.setenv('DAN_BROWSER_RECIPES_DIR', str(tmp_path/'recipes'))
    monkeypatch.delenv('DAN_COMMAND_JOB_ID', raising=False)
    monkeypatch.setattr('app.tools.browser._browser_room_id', lambda: '')
    jev = FakeJev()

    class Decisions:
        def __init__(self, *a, **k): self.calls = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def choose(self, state, questions):
            self.calls += 1
            return await jev.choose(state, questions)
    monkeypatch.setattr('app.services.jev_decisions.Decisions', Decisions)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.route(ORIGIN+'/**', lambda route: route.fulfill(content_type='text/html; charset=utf-8',
            body='<meta charset="utf-8">'+PAGES.get(route.request.url.split(ORIGIN)[1].split('?')[0], '<title>404</title><h1>404</h1>')))
        monkeypatch.setattr('app.tools.browser.get_executor_page', AsyncMock(return_value=PageAdapter(page)))
        await _execute_browser_tool('open', {'url': ORIGIN+'/home', 'observation': 'dom'})
        try:
            yield page, jev
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_exact_path_needs_no_model_at_all(site):
    page, jev = site
    result = await _execute_browser_tool('follow', {'path': ['口座情報・入出金', '入出金明細', '絞り込み']})
    assert result['follow']['completed'] and result['follow']['pressed'] == ['口座情報・入出金', '入出金明細', '絞り込み']
    assert jev.calls == 0 and await page.inner_text('#range') == '9月の明細を表示中'
    assert any(b['type'] == 'image' for b in result['content'])  # the large model verifies the final screen itself


@pytest.mark.asyncio
async def test_loose_wording_is_matched_by_jev(site):
    page, jev = site
    jev.rules = [('口座の情報', '口座情報・入出金'), ('明細', '入出金明細')]
    result = await _execute_browser_tool('follow', {'path': ['口座の情報', '明細を見る']})
    assert result['follow']['completed'] and page.url == ORIGIN+'/statement' and jev.calls == 2
    state, question = jev.asked[0]
    assert 'page_text' not in state and '口座の情報' in question['instructions']  # label matching sends labels only


@pytest.mark.asyncio
async def test_goal_walks_until_jev_says_done_and_twins_are_told_apart(site):
    page, jev = site
    jev.rules = [('"already_pressed": []', '口座情報・入出金'), ('"already_pressed": ["口座情報・入出金"]', '入出金明細'),
                 ('"already_pressed": ["口座情報・入出金", "入出金明細"]', 'B社'), ('B社の詳細', 'already achieved')]
    result = await _execute_browser_tool('follow', {'goal': 'B社の取引の詳細を開く'})
    assert result['follow']['completed'] and page.url == ORIGIN+'/detail/b'
    twins = [v for v in jev.asked[2][1]['criteria'].values() if '詳細' in v]
    assert len(twins) == 2 and all('inside' in v for v in twins)


@pytest.mark.asyncio
async def test_doubt_sensitive_buttons_and_dead_clicks_stop_the_walk(site):
    page, jev = site
    jev.rules = [('口座', '口座情報・入出金')]
    jev.confidence = .7
    unsure = await _execute_browser_tool('follow', {'path': ['口座のページ']})
    assert unsure['follow']['reason'] == 'uncertain' and unsure['follow']['pressed'] == [] and page.url == ORIGIN+'/home'

    jev.confidence = .99
    sent = await _execute_browser_tool('follow', {'path': ['口座情報・入出金', '入出金明細', '送信']})
    assert sent['follow']['reason'] == 'sensitive_action_needs_agent' and sent['follow']['pressed'] == ['口座情報・入出金', '入出金明細']
    assert sent['follow']['remaining'] == ['送信'] and await page.title() == '入出金明細'  # 送信 was not pressed
    assert '既に押してあります' in sent['content'][0]['text']

    dead = await _execute_browser_tool('follow', {'path': ['何も起きないボタン', '絞り込み']})
    assert dead['follow']['reason'] == 'no_visible_change' and dead['follow']['pressed'] == ['何も起きないボタン']

    missing = await _execute_browser_tool('follow', {'path': ['存在しないメニュー']})
    assert missing['follow']['reason'] == 'no_matching_element'


@pytest.mark.asyncio
async def test_login_pages_and_bad_arguments(site):
    page, jev = site
    await page.goto(ORIGIN+'/secure')
    login = await _execute_browser_tool('follow', {'path': ['戻る']})
    assert login['follow']['reason'] == 'login_needs_agent' and page.url == ORIGIN+'/secure'
    assert (await _execute_browser_tool('follow', {}))['success'] is False
    assert (await _execute_browser_tool('follow', {'path': []}))['success'] is False
    assert (await _execute_browser_tool('follow', {'goal': 'x', 'max_steps': 99}))['success'] is False
