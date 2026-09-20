import asyncio
import copy
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from app.services import browser_plan as plan
from app.services.jev_decisions import choice_answers
from app.services.cancellation import CancellationRegistry
from app.tools.browser import _execute_page_command


class PageAdapter:
    """Exercise the real executor/actions on an isolated browser, never Core."""
    def __init__(self, page):
        self.page = page
        self.state = {'current': page, 'all_pages': [page]}

    @property
    def url(self):
        return self.page.url

    async def command(self, cmd, **args):
        return await _execute_page_command(self.state, self.page.context, cmd, args)

    async def evaluate(self, expression, arg=None):
        return (await self.command('evaluate', expression=expression, arg=arg)).get('result')

    async def get_interactive_elements(self):
        return (await self.command('get_interactive_elements'))['elements']

    async def get_page_context(self):
        return (await self.command('get_page_context'))['context']

    async def screenshot_base64(self, full_page=False):
        return await self.command('screenshot_base64', full_page=full_page)

    async def wait_for_load_state(self, state, timeout=None):
        return await self.command('wait_for_load_state', state=state, timeout=timeout)

    async def wait_for_timeout(self, timeout):
        return await self.command('wait_for_timeout', timeout=timeout)

    async def check_condition_before_action(self, condition):
        return await self.command('check_condition_before_action', condition=condition)

    async def wait_for_condition(self, condition):
        return await self.command('wait_for_condition', condition=condition)

    async def guarded_click(self, ref, timeout):
        return await self.command('guarded_click', ref=ref, timeout=timeout)

    async def get_tab_count(self):
        return await self.command('get_tab_count')

    async def fill_form(self, fields, expected_url):
        return await self.command('fill_form', fields=fields, expected_url=expected_url)

    async def fill_by_ref(self, ref, value):
        return await self.command('fill_by_ref', ref=ref, value=value)

    async def goto(self, url):
        return await self.command('goto', url=url)


@pytest_asyncio.fixture
async def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('DAN_BROWSER_TIMING_LOG', str(tmp_path/'timing.jsonl'))
    monkeypatch.delenv('DAN_COMMAND_JOB_ID', raising=False)
    monkeypatch.setattr('app.tools.browser._browser_room_id', lambda: '')
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        proxy = PageAdapter(page)
        monkeypatch.setattr('app.tools.browser.get_executor_page', AsyncMock(return_value=proxy))
        try:
            yield page, proxy
        finally:
            await browser.close()


def candidate(name, role='textbox'):
    return {'role': role, 'name': name}


def form_plan(*names):
    return {'expected_url': 'about:blank', 'steps': [{'action': 'fill_form', 'fields': [
        {'target': name, 'candidates': [candidate(name)], 'value': 'value-'+name} for name in names]}]}


def decision(questions, selected='0', confidence=1):
    return {'available': True, 'answers': {key: {
        'type': 'choice', 'choice': selected, 'confidence': confidence,
        'probabilities': {k: 1 if k==selected else 0 for k in q['criteria']}}
        for key,q in questions.items()}}


@pytest.mark.asyncio
async def test_real_form_and_final_image_without_model(isolated, monkeypatch):
    page, _ = isolated
    await page.set_content('<label>氏名<input></label><label>都市<input></label><button onclick="window.sent=true">送信</button>')
    choose = AsyncMock(side_effect=AssertionError('No model needed for unique targets'))
    monkeypatch.setattr(plan.Decisions, 'choose', choose)
    result = await plan.run(form_plan('氏名', '都市'))
    assert result['success'], result
    assert result['completed'] == [1]
    assert await page.locator('input').evaluate_all('els=>els.map(e=>e.value)') == ['value-氏名', 'value-都市']
    assert not await page.evaluate('!!window.sent')
    assert any(c['type']=='image' for c in result['content'])
    choose.assert_not_called()


@pytest.mark.asyncio
async def test_one_call_batches_semantic_field_choices(isolated, monkeypatch):
    page, _ = isolated
    await page.set_content('<label>姓<input></label><label>名<input></label>')
    args = form_plan('姓','名')
    for f in args['steps'][0]['fields']:
        f['candidates'] = [candidate('姓'),candidate('名')]
    async def choose(self, state, questions):
        assert len(questions)==2
        self.calls += 1
        result = decision(questions)
        result['answers']['1'] = decision({'1':questions['1']},'1')['answers']['1']
        return result
    monkeypatch.setattr(plan.Decisions,'choose',choose)
    result = await plan.run(args)
    assert result['success'] and result['decision_calls']==1
    assert await page.locator('input').evaluate_all('els=>els.map(e=>e.value)') == ['value-姓','value-名']


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['uncertain','changed','duplicate','unavailable','cancel'])
async def test_no_mutation_on_uncertain_or_stale_selection(isolated, monkeypatch, mode):
    page, _ = isolated
    await page.set_content('<label>A<input></label><label>B<input></label>')
    args = form_plan('A','B')
    for f in args['steps'][0]['fields']: f['candidates'] = [candidate('A'),candidate('B')]
    async def choose(self, state, questions):
        if mode=='changed': await page.locator('input').first.evaluate("e=>e.outerHTML='<input>'")
        if mode=='unavailable': return {'available':False,'reason':'unavailable'}
        if mode=='cancel': CancellationRegistry.cancel('plan-test')
        return decision(questions, confidence=.2 if mode=='uncertain' else 1)
    monkeypatch.setattr(plan.Decisions,'choose',choose)
    CancellationRegistry.register('plan-test')
    CancellationRegistry.set_current_session('plan-test')
    try:
        result = await plan.run(args)
        assert not result['success'] and result['completed']==[]
        assert await page.locator('input').evaluate_all('els=>els.every(e=>e.value==="")')
    finally:
        CancellationRegistry.unregister('plan-test')
        CancellationRegistry.set_current_session(None)


@pytest.mark.asyncio
async def test_sensitive_click_and_protected_field_handoff(isolated):
    page, _ = isolated
    await page.set_content('<button onclick="window.sent=true">購入を確定</button><label>Code<input autocomplete="one-time-code"></label><p id="result">ready</p>')
    result = await plan.run({'expected_url':page.url,'steps':[{'action':'click','target':'購入を確定',
        'candidates':[candidate('購入を確定','button')], 'expect':{'selector':'#result','text':'done'}}]})
    assert result['reason']=='sensitive_action_needs_agent'
    assert not await page.evaluate('!!window.sent')
    result = await plan.run(form_plan('Code'))
    assert result['reason']=='protected_field'
    assert await page.locator('input').input_value()==''


@pytest.mark.asyncio
async def test_failed_postcondition_never_replays_click_or_next_step(isolated):
    page, _ = isolated
    await page.set_content('<button onclick="window.count=(window.count||0)+1">Next</button><p id="result">ready</p><label>A<input></label>')
    args = form_plan('A')
    args['steps'].insert(0,{'action':'click','target':'Next','candidates':[candidate('Next','button')],
                          'expect':{'selector':'#result','text':'done','timeout_ms':50}})
    result = await plan.run(args)
    assert not result['success'] and result['completed']==[]
    assert await page.evaluate('window.count')==1
    assert await page.locator('input').input_value()==''


@pytest.mark.asyncio
async def test_complete_validation_before_first_mutation(isolated):
    page, _ = isolated
    await page.set_content('<label>A<input></label>')
    args=form_plan('A')
    args['steps'].append({'action':'evaluate','script':'invalid'})
    with pytest.raises(ValueError): await plan.run(args)
    assert await page.locator('input').input_value()==''


@pytest.mark.asyncio
async def test_ready_uses_specific_evidence_without_claiming_authentication(isolated, tmp_path, monkeypatch):
    from app.agent.v2.tools import _execute_browser_tool
    page, proxy = isolated
    fixture=tmp_path/'ready.html'
    fixture.write_text('<h1 id="destination" hidden>Account fixture</h1><script>setTimeout(()=>document.querySelector("h1").hidden=false,150)</script>',encoding='utf-8')
    wait=AsyncMock(side_effect=AssertionError('No fixed delay for explicit readiness'))
    monkeypatch.setattr(proxy,'wait_for_timeout',wait)
    result=await _execute_browser_tool('open_target',{'url':fixture.as_uri(),'ready':{'selector':'#destination','text':'Account fixture'},'observation':'dom'})
    assert result['success'] and result['ready_verified']
    assert result['authentication']=='unverified'
    wait.assert_not_called()


@pytest.mark.asyncio
async def test_missing_ready_evidence_fails_without_retry(isolated, tmp_path, monkeypatch):
    from app.agent.v2 import tools
    page, proxy = isolated
    fixture=tmp_path/'ready-missing.html'
    fixture.write_text('<h1>Other page</h1>',encoding='utf-8')
    goto=AsyncMock(wraps=proxy.goto)
    monkeypatch.setattr(proxy,'goto',goto)
    result=await tools._execute_browser_tool('open_target',{'url':fixture.as_uri(),'ready':{'selector':'#destination','timeout_ms':50},'observation':'dom'})
    assert not result['success'] and result['reason']=='destination_condition_unverified'
    assert tools._browser_auth_state['target_url']==fixture.as_uri()
    goto.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_ready_retains_delayed_redirect_grace(isolated, tmp_path, monkeypatch):
    from app.agent.v2.tools import _execute_browser_tool
    _, proxy = isolated
    fixture=tmp_path/'plain.html'
    fixture.write_text('<h1>Ready</h1>',encoding='utf-8')
    wait=AsyncMock()
    monkeypatch.setattr(proxy,'wait_for_timeout',wait)
    result=await _execute_browser_tool('open_target',{'url':fixture.as_uri(),'observation':'dom'})
    assert result['success']
    assert wait.await_count==29


@pytest.mark.asyncio
async def test_job_update_stops_remaining_plan_without_waiting_for_application(isolated, tmp_path, monkeypatch):
    import uuid
    from app.services import command_job_state as state
    from app.agent.v2 import tools
    page,_=isolated
    await page.set_content('<label>A<input></label><label>B<input></label>')
    monkeypatch.setattr(state,'ROOT',tmp_path/'jobs')
    job=str(uuid.uuid4());state.create(job,user_id='u',origin_room_id='r',state='running')
    monkeypatch.setenv('DAN_COMMAND_JOB_ID',job)
    original=tools._execute_browser_tool
    async def execute(action,args):
        result=await original(action,args)
        if action=='fill_form':state.control(job,'u','r','update','Use different details')
        return result
    monkeypatch.setattr(tools,'_execute_browser_tool',execute)
    args=form_plan('A')
    args['steps'].extend(form_plan('B')['steps'])
    result=await asyncio.wait_for(plan.run(args),timeout=2)
    assert result['reason']=='instructions_changed' and result['completed']==[1]
    assert await page.locator('input').nth(1).input_value()==''
    formatted=tools.format_tool_result(result,'_browser','run_plan')
    assert 'instructions_changed' in formatted.text and '"completed": [1]' in formatted.text


def test_plan_discovery_has_required_url_and_steps():
    from app.agent.v2.tools import get_all_skill_tools,parse_tool_name
    discovered=next(t for t in get_all_skill_tools() if t['name']=='browser_plan')
    assert discovered['input_schema']['required']==['expected_url','steps']
    assert parse_tool_name('browser_plan')==('_browser','run_plan')


@pytest.mark.asyncio
async def test_plan_only_turn_is_counted_in_request_timings(monkeypatch, tmp_path):
    import json
    from app.tools.browser_metrics import measure_browser_request
    path=tmp_path/'timings.jsonl';monkeypatch.setenv('DAN_BROWSER_TIMING_LOG',str(path))
    @measure_browser_request
    async def turn():
        yield {'type':'tool_use','name':'mcp__dan__browser_plan'}
        yield {'type':'result','is_error':False}
    assert len([event async for event in turn()])==2
    row=json.loads(path.read_text(encoding='utf-8').splitlines()[-1])
    assert row['browser_calls']==1 and row['status']=='returned'


@pytest.mark.asyncio
async def test_dom_final_retains_actual_evidence_and_verified_conditions(isolated):
    from app.agent.v2.tools import format_tool_result
    page,_=isolated
    await page.set_content('<button onclick="document.querySelector(\'#result\').textContent=\'Done\'">Next</button><p id="result">Ready</p>')
    result=await plan.run({'expected_url':page.url,'final_observation':'dom','steps':[
        {'action':'click','target':'Next','candidates':[candidate('Next','button')],'expect':{'selector':'#result','text':'Done'}}]})
    assert result['success'] and result['verified_conditions']==[{'step':1,'selector':'#result','text':'Done'}]
    formatted=format_tool_result(result,'_browser','run_plan')
    assert 'Done' in formatted.text and '"completed": [1]' in formatted.text
    assert not formatted.images


@pytest.mark.parametrize('mutation', ['missing','nan','wrong_max','out_of_set','confidence_bool'])
def test_distribution_validation(mutation):
    questions={'target':{'criteria':{'0':'a','1':'b','none':'unknown'}}}
    data=decision(questions)
    a=data['answers']['target']
    if mutation=='missing': a['probabilities'].pop('none')
    if mutation=='nan': a['probabilities']['0']=float('nan')
    if mutation=='wrong_max': a['choice']='1'
    if mutation=='out_of_set': a['choice']='99'
    if mutation=='confidence_bool': a['confidence']=True
    with pytest.raises(ValueError): choice_answers(data,questions)


@pytest.mark.asyncio
async def test_decision_timeout_has_no_retry(monkeypatch):
    from app.services.jev_decisions import Decisions
    async def slow(self):
        await asyncio.sleep(1)
    monkeypatch.setattr(Decisions,'_credential',slow)
    async with Decisions('test',timeout=.02,enabled=True) as client:
        result=await client.choose({}, {'q':{'type':'choice','criteria':{'yes':'Yes','no':'No'}}})
        assert not result['available'] and result['elapsed_ms']<200
        assert client.calls==0
        assert (await client.choose({}, {}))['reason']=='decision_budget'
