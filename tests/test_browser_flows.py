"""A multi-step operation the model did once (a timetable search) is remembered and replayed by code with new values."""
import json

import pytest

from app.agent.v2.tools import _execute_browser_tool
from app.services import browser_flows as flows
from tests.test_browser_replay import bank as site_fixture, ref, ORIGIN  # noqa: F401  (fixture, browser)

SEARCH = '''<h1>架空鉄道 時刻表検索</h1>
<label>出発駅<input id="from"></label><label>到着駅<input id="to"></label>
<label>出発日<select id="date"><option value="0924">9月24日</option><option value="0925">9月25日</option></select></label>
<div id="cal">'''+''.join(f'<button type="button" onclick="document.getElementById(&quot;day&quot;).value=this.textContent">{d}</button>' for d in range(1, 31))+'''</div><input type="hidden" id="day">
<button id="go" onclick="location.href='/result?from='+encodeURIComponent(document.querySelector('#from').value)+'&to='+encodeURIComponent(document.querySelector('#to').value)+'&d='+document.querySelector('#date').value+'&day='+document.querySelector('#day').value">検索</button>'''


import pytest_asyncio


@pytest_asyncio.fixture
async def rail(site_fixture, monkeypatch, tmp_path):
    page, site, _ = site_fixture
    monkeypatch.setenv('DAN_BROWSER_FLOWS_DIR', str(tmp_path/'flows'))
    monkeypatch.setenv('DAN_COMMAND_JOB_ID', 'job-flow')
    monkeypatch.setattr('app.services.command_job_state.read', lambda job_id: {'task': '今回のユーザー発言（原文）:\n新大阪から品川の便を調べて'})
    original = site.handle
    async def handle(route):
        path = route.request.url.split(ORIGIN)[1]
        if path.startswith('/search'): return await route.fulfill(content_type='text/html; charset=utf-8', body='<meta charset="utf-8">'+SEARCH)
        if path.startswith('/result'):
            from urllib.parse import urlsplit, parse_qs
            q = parse_qs(urlsplit(route.request.url).query)
            day = (q.get('day') or [''])[0]
            return await route.fulfill(content_type='text/html; charset=utf-8', body=f'<meta charset="utf-8"><h1>検索結果</h1><p>{q["from"][0]}→{q["to"][0]} {q["d"][0]}{(" day"+day) if day else ""}: のぞみ1号 06:00</p><a href="/search">再検索</a>')
        return await original(route)
    from app.tools import browser as B
    proxy = await B.get_executor_page()
    if not hasattr(proxy, 'locator'): proxy.locator = page.locator   # the executor's select uses page.locator
    if not hasattr(proxy, 'mouse'): proxy.mouse = page.mouse   # a coordinate click uses page.mouse
    await page.route(ORIGIN+'/search*', handle)
    await page.route(ORIGIN+'/result*', handle)
    return page, tmp_path/'flows'


@pytest.mark.asyncio
async def test_search_done_once_is_replayed_with_new_values_and_no_model(rail):
    page, directory = rail
    # the model, by hand, the first time
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/search', 'login': False})
    await _execute_browser_tool('type', {'ref': await ref(page, '#from'), 'text': '新大阪'})
    await _execute_browser_tool('type', {'ref': await ref(page, '#to'), 'text': '品川'})
    await _execute_browser_tool('read', {})   # the model looks at the page mid-way: the flow is not finished here
    await _execute_browser_tool('select', {'ref': await ref(page, '#date'), 'value': '0924'})
    await _execute_browser_tool('click', {'ref': await ref(page, '#go')})
    await _execute_browser_tool('read', {})
    await _execute_browser_tool('release', {})
    assert '新大阪' not in (directory/'bank.example.test.json').read_text(encoding='utf-8')   # encrypted at rest
    saved = flows.flows_for('bank.example.test')
    assert len(saved) == 1
    flow = saved[0]
    assert [s['action'] for s in flow['steps']] == ['type', 'type', 'select', 'click']
    assert flow['slots'] == {'出発駅': '新大阪', '到着駅': '品川', 'date': '0924'} and flow['name'] == '新大阪から品川の便を調べて'
    # the second time: code, new values
    result = await flows.run(flow, {'出発駅': '東京', '到着駅': '博多', 'date': '0925'})
    assert result['replayed'], result
    assert '東京→博多 0925' in await page.inner_text('body')
    listed = (await flows.tool({'action': 'list'}))['output']
    assert '出発駅（例: 新大阪）' in listed and flow['id'] in listed


@pytest.mark.asyncio
async def test_secrets_typed_by_hand_are_never_part_of_a_flow(rail):
    page, directory = rail
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/login', 'login': False})
    await _execute_browser_tool('type', {'ref': await ref(page, '#user'), 'text': 'someone'})
    await _execute_browser_tool('type', {'ref': await ref(page, '#pw'), 'text': 'hunter2'})
    await _execute_browser_tool('read', {})
    await _execute_browser_tool('release', {})
    assert 'hunter2' not in json.dumps(flows.flows_for('bank.example.test'), ensure_ascii=False)


@pytest.mark.asyncio
async def test_login_clicks_are_the_login_recipes_business_not_a_flow(rail):
    """Typing on a login page (an ID) is never a flow step; a lone click there is not enough for a flow."""
    page, directory = rail
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/login', 'login': False})
    await _execute_browser_tool('type', {'ref': await ref(page, '#user'), 'text': 'someone'})
    await _execute_browser_tool('click', {'ref': await ref(page, '#user')})
    await _execute_browser_tool('read', {})
    await _execute_browser_tool('release', {})
    assert not (directory/'bank.example.test.json').exists()


@pytest.mark.asyncio
async def test_after_a_replayed_login_the_task_that_follows_is_still_recorded(rail, monkeypatch):
    """The login replay deletes the half-run so it cannot become a recipe; the task after it must start a new run."""
    from app.services import browser_recipes as recipes
    page, directory = rail
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/search', 'login': False})
    # what browser_replay.run does at the end of a successful login: the run is gone, a new one starts logged in
    recipes._run_file().unlink(missing_ok=True)
    recipes.start_run(None, recipes.url_key(page.url), login_over=True)
    await _execute_browser_tool('type', {'ref': await ref(page, '#from'), 'text': '新大阪'})
    await _execute_browser_tool('type', {'ref': await ref(page, '#to'), 'text': '品川'})
    await _execute_browser_tool('click', {'ref': await ref(page, '#go')})
    await _execute_browser_tool('read', {})
    saved = flows.flows_for('bank.example.test')
    assert [s['action'] for s in saved[0]['steps']] == ['type', 'type', 'click'] and saved[0]['slots'] == {'出発駅': '新大阪', '到着駅': '品川'}


@pytest.mark.asyncio
async def test_a_click_reported_failed_that_moved_the_page_is_still_a_step(rail):
    """Sites navigate after a click whose `expect` never came true: the tool says failed, the page moved on. It happened."""
    page, directory = rail
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/search', 'login': False})
    await _execute_browser_tool('type', {'ref': await ref(page, '#from'), 'text': '新大阪'})
    await _execute_browser_tool('type', {'ref': await ref(page, '#to'), 'text': '品川'})
    outcome = await _execute_browser_tool('click', {'ref': await ref(page, '#go'), 'expect': {'selector': '#never-appears', 'state': 'visible', 'timeout_ms': 100}})
    assert outcome.get('success') is False and '/result' in page.url
    await _execute_browser_tool('read', {})
    saved = flows.flows_for('bank.example.test')
    assert [s['action'] for s in saved[0]['steps']] == ['type', 'type', 'click']


@pytest.mark.asyncio
async def test_a_click_by_coordinates_is_recorded_as_the_element_under_the_point(rail):
    page, directory = rail
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/search', 'login': False})
    await _execute_browser_tool('type', {'ref': await ref(page, '#from'), 'text': '新大阪'})
    await _execute_browser_tool('type', {'ref': await ref(page, '#to'), 'text': '品川'})
    box = await page.locator('#go').bounding_box()
    await _execute_browser_tool('click', {'x': int(box['x']+box['width']/2), 'y': int(box['y']+box['height']/2)})
    await _execute_browser_tool('read', {})
    saved = flows.flows_for('bank.example.test')
    assert [s['action'] for s in saved[0]['steps']] == ['type', 'type', 'click'] and saved[0]['steps'][2]['targets']['ref']['name'] == '検索'


@pytest.mark.asyncio
async def test_a_failed_flow_is_superseded_by_the_next_recording_of_the_same_task(rail):
    page, directory = rail
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/search', 'login': False})
    await _execute_browser_tool('type', {'ref': await ref(page, '#from'), 'text': '新大阪'})
    await _execute_browser_tool('type', {'ref': await ref(page, '#to'), 'text': '品川'})
    await _execute_browser_tool('click', {'ref': await ref(page, '#go')})
    await _execute_browser_tool('read', {})
    await _execute_browser_tool('release', {})
    first = flows.flows_for('bank.example.test')[0]
    flows.report(first, False)   # its replay failed once: still listed, the model does the task by hand
    assert [f['id'] for f in flows.all_flows()] == [first['id']]
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/search', 'login': False})
    await _execute_browser_tool('type', {'ref': await ref(page, '#from'), 'text': '新大阪'})
    await _execute_browser_tool('type', {'ref': await ref(page, '#to'), 'text': '品川'})
    await _execute_browser_tool('select', {'ref': await ref(page, '#date'), 'value': '0925'})   # done differently this time
    await _execute_browser_tool('click', {'ref': await ref(page, '#go')})
    await _execute_browser_tool('read', {})
    await _execute_browser_tool('release', {})
    listed = flows.all_flows()
    assert len(listed) == 1 and listed[0]['id'] != first['id'] and listed[0]['slots'] == {'出発駅': '新大阪', '到着駅': '品川', 'date': '0925'}


@pytest.mark.asyncio
async def test_a_calendar_day_clicked_is_a_slot_and_replays_with_another_day(rail):
    """The name clicked among a set of short-named siblings (a calendar's days) is the value; the replay clicks the day asked for."""
    page, directory = rail
    await _execute_browser_tool('open_target', {'url': ORIGIN+'/search', 'login': False})
    await _execute_browser_tool('type', {'ref': await ref(page, '#from'), 'text': '新大阪'})
    await _execute_browser_tool('type', {'ref': await ref(page, '#to'), 'text': '品川'})
    day25 = await page.get_attribute('#cal button:nth-child(25)', 'data-dan-ref')
    await _execute_browser_tool('click', {'ref': '@'+day25})
    await _execute_browser_tool('click', {'ref': await ref(page, '#go')})
    await _execute_browser_tool('read', {})
    flow = flows.flows_for('bank.example.test')[0]
    assert flow['slots'] == {'出発駅': '新大阪', '到着駅': '品川', '選択1': '25'} and '候補: 1/2/3' in flows.describe(flow)
    result = await flows.run(flow, {'選択1': '26'})
    assert result['replayed'], result
    assert '新大阪→品川 0924 day26' in await page.inner_text('body')
