import pytest

from tests.test_browser_plan import isolated, candidate, decision
from app.services import browser_flow as flow


def request():
    return {'expected_url':'about:blank','goal':'Reach Step 3 using Next',
            'candidates':[candidate('Next','button'),candidate('Back','button')],
            'until':{'selector':'#stage','text':'Step 3'},'max_steps':3}


async def fixture_page(page):
    await page.set_content('''<h1 id="stage">Step 0</h1>
        <button onclick="window.n++;document.querySelector('#stage').textContent='Step '+window.n">Next</button>
        <button onclick="window.wrong++">Back</button>''')
    await page.evaluate('window.n=0;window.wrong=0')


@pytest.mark.asyncio
async def test_closed_loop_checks_actual_goal_and_one_final_image(isolated,monkeypatch):
    page,_=isolated
    await fixture_page(page)
    async def choose(self,state,questions):
        self.calls+=1
        assert 'Step '+str(self.calls-1) in state['current_page_text']
        return decision(questions)
    monkeypatch.setattr(flow.Decisions,'choose',choose)
    result=await flow.run(request())
    assert result['success'] and result['decision_calls']==3, result
    assert len(result['completed'])==3
    assert await page.evaluate('window.n===3 && window.wrong===0')
    assert any(c['type']=='image' for c in result['content'])
    assert result['observed_goal_text']=='Step 3'


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['unavailable','uncertain','changed','none'])
async def test_decision_failure_never_clicks(isolated,monkeypatch,mode):
    page,_=isolated
    await fixture_page(page)
    async def choose(self,state,questions):
        if mode=='unavailable':return {'available':False,'reason':'timeout'}
        if mode=='changed':await page.locator('#stage').evaluate("e=>e.textContent='Changed'")
        return decision(questions,selected='none' if mode=='none' else '0',confidence=.5 if mode=='uncertain' else 1)
    monkeypatch.setattr(flow.Decisions,'choose',choose)
    result=await flow.run(request())
    assert not result['success'] and not result['completed']
    assert await page.evaluate('window.n===0 && window.wrong===0')


@pytest.mark.asyncio
async def test_no_progress_click_is_not_replayed(isolated,monkeypatch):
    page,_=isolated
    await fixture_page(page)
    await page.get_by_role('button',name='Next',exact=True).evaluate("e=>e.onclick=()=>window.n++")
    async def choose(self,state,questions):return decision(questions)
    monkeypatch.setattr(flow.Decisions,'choose',choose)
    result=await flow.run(request())
    assert result['reason']=='no_observed_progress'
    assert result['uncertain_step']==1 and result['retry_safe'] is False
    assert await page.evaluate('window.n')==1


@pytest.mark.asyncio
async def test_authentication_never_reaches_jev(isolated,monkeypatch):
    page,_=isolated
    await fixture_page(page)
    await page.evaluate("document.body.insertAdjacentHTML('beforeend','<input type=password>')")
    async def choose(*args):raise AssertionError('No API call on authentication page')
    monkeypatch.setattr(flow.Decisions,'choose',choose)
    result=await flow.run(request())
    assert result['reason']=='authentication_needs_agent'
    assert await page.evaluate('window.n')==0


@pytest.mark.asyncio
@pytest.mark.parametrize('missing',[False,True])
async def test_scoped_instruction_and_single_candidate(isolated,monkeypatch,missing):
    page,_=isolated
    await fixture_page(page)
    args=request();args['instruction_selector']='#absent' if missing else '#stage'
    args['candidates']=[candidate('Next','button')]
    async def choose(self,state,questions):
        assert not missing
        assert 'Step ' in questions['next']['instructions']
        assert 'current_page_text' not in state and state['current_requirement'].startswith('Step ')
        assert set(questions['next']['criteria'])=={'0','none'}
        return decision(questions)
    monkeypatch.setattr(flow.Decisions,'choose',choose)
    result=await flow.run(args)
    assert result['success']==(not missing)
    assert await page.evaluate('window.n')==(0 if missing else 3)


@pytest.mark.asyncio
async def test_false_completion_and_step_limit(isolated,monkeypatch):
    page,_=isolated
    await fixture_page(page)
    async def choose(self,state,questions):return decision(questions)
    monkeypatch.setattr(flow.Decisions,'choose',choose)
    params=request();params['max_steps']=1
    result=await flow.run(params)
    assert result['reason']=='step_limit' and not result['success']
    assert result['verified_condition'] is None
    assert await page.evaluate('window.n')==1


def test_flow_exposed_only_when_enabled(monkeypatch,tmp_path):
    from app.agent.v2.tools import get_all_skill_tools,parse_tool_name
    monkeypatch.delenv('DAN_JEV_BROWSER_ENABLED',raising=False)
    monkeypatch.setattr('app.services.jev_browser_budget.PATH',tmp_path/'missing.json')
    assert 'browser_flow' not in {t['name'] for t in get_all_skill_tools()}
    monkeypatch.setenv('DAN_JEV_BROWSER_ENABLED','1')
    assert 'browser_flow' in {t['name'] for t in get_all_skill_tools()}
    assert parse_tool_name('browser_flow')==('_browser','run_flow')


@pytest.mark.asyncio
async def test_instruction_update_during_choice_prevents_click(isolated,monkeypatch,tmp_path):
    import uuid
    from app.services import command_job_state as jobs
    page,_=isolated
    await fixture_page(page)
    monkeypatch.setattr(jobs,'ROOT',tmp_path/'jobs')
    job=str(uuid.uuid4());jobs.create(job,user_id='u',origin_room_id='r',state='running')
    monkeypatch.setenv('DAN_COMMAND_JOB_ID',job)
    async def choose(self,state,questions):
        jobs.control(job,'u','r','update','Stop going forward')
        return decision(questions)
    monkeypatch.setattr(flow.Decisions,'choose',choose)
    result=await flow.run(request())
    assert result['reason']=='instructions_changed'
    assert await page.evaluate('window.n')==0


@pytest.mark.asyncio
async def test_disabled_client_never_reads_key_or_sends_request(monkeypatch,tmp_path):
    from app.services.jev_decisions import Decisions
    from unittest.mock import AsyncMock
    monkeypatch.delenv('DAN_JEV_BROWSER_ENABLED',raising=False)
    monkeypatch.setattr('app.services.jev_browser_budget.PATH',tmp_path/'missing.json')
    read=AsyncMock(side_effect=AssertionError('disabled'))
    monkeypatch.setattr(Decisions,'_credential',read)
    async with Decisions('user') as client:
        result=await client.choose({}, {'next':{'type':'choice','criteria':{'0':'Next','none':'none'}}})
        assert result['reason']=='disabled' and client.calls==0
    read.assert_not_called()
