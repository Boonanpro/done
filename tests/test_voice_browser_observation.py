from unittest.mock import AsyncMock
import pytest
from app.agent.v2 import tools

@pytest.mark.asyncio
async def test_dom_mode_keeps_verified_elements_and_explicit_screenshot(monkeypatch):
    page=AsyncMock()
    page.url='https://example.com'
    page.get_interactive_elements.return_value=[{'ref':'@a:1','tag':'button','text':'予約一覧'}]
    page.get_page_context.return_value={'headings':[{'level':1,'text':'予約詳細'}]}
    page.evaluate.return_value={'title':'Test','text':'14号車11E席 14920円'}
    page.screenshot_base64.return_value={'base64':'aW1hZ2U=','media_type':'image/png'}
    monkeypatch.setenv('DAN_BROWSER_OBSERVATION','dom')
    monkeypatch.setattr('app.tools.browser._browser_room_id',lambda:'')
    async def observe(action,params): return await tools._get_browser_state(page)
    monkeypatch.setattr(tools,'_execute_browser_tool_impl',observe)
    result=await tools._execute_browser_tool('click',{'ref':'@a:1'})
    assert not any(c['type']=='image' for c in result['content'])
    assert '@a:1' in result['content'][-1]['text'] and '予約詳細' in result['content'][-1]['text']
    assert '14920円' in result['content'][-1]['text']
    page.screenshot_base64.assert_not_called()
    full=await tools._execute_browser_tool('screenshot',{})
    assert any(c['type']=='image' for c in full['content'])
    page.screenshot_base64.assert_awaited_once()
    assert tools._browser_observation.get()=='full'
