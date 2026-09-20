import asyncio,uuid
from unittest.mock import AsyncMock
import pytest
from app.services import browser_script as script,command_job_state as state,command_job_tools as gate

@pytest.mark.parametrize('code',['import os','await page.evaluate("fetch(\"/buy\")")','await page.get_by_role("button",name="Buy").__class__()','await page.goto(__import__("os").getenv("HOME"))','while True: pass'])
def test_rejects_uncontrolled_code_before_running(code):
    with pytest.raises((ValueError,SyntaxError)):script.parse(code)

@pytest.mark.asyncio
async def test_update_stops_remaining_script_and_confirmation_is_not_bypassed(tmp_path,monkeypatch):
    monkeypatch.setattr(state,'ROOT',tmp_path)
    job=str(uuid.uuid4());state.create(job,user_id='u',origin_room_id='r',state='running')
    monkeypatch.setattr('app.tools.browser.get_executor_page',AsyncMock())
    monkeypatch.setattr(script,'resolve',AsyncMock(return_value='@buy'))
    monkeypatch.setattr(gate,'browser_target',AsyncMock(return_value={'url':'https://example.com','label':'購入を確定','body':'100円'}))
    executed=AsyncMock(return_value={'success':True});monkeypatch.setattr('app.agent.v2.tools._execute_browser_tool',executed)
    task=asyncio.create_task(script.run(job,'await page.get_by_role("button", name="購入を確定").click()'))
    await asyncio.sleep(.15)
    executed.assert_not_called()
    state.control(job,'u','r','cancel')
    result=await task
    assert not result['success'] and not result['completed']
    other=str(uuid.uuid4());state.create(other,user_id='u',origin_room_id='r',state='running')
    async def operation(*args):
        state.control(other,'u','r','update','stop old steps')
        state.change(other,lambda s:s.update(applied_revision=s['revision']))
        return {'success':True}
    executed.side_effect=operation
    result=await script.run(other,'await page.goto("https://example.com")\nawait page.goto("https://example.org")')
    assert result['completed']==[1] and not result['success'] and executed.await_count==1
