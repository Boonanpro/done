import asyncio
import os
import time
import pytest
from app.services import voice_screen_stream as S

@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'directory', lambda room: tmp_path / room)
    return tmp_path

@pytest.mark.asyncio
async def test_frames_are_room_scoped_and_length_delimited(root):
    key='a'*32
    S.write_frame('a',key,b'one')
    S.write_frame('b',key,b'two')
    async def connected(): return False
    gen=S.frames('a',key,connected)
    first=await anext(gen)
    assert first.endswith(b'one\r\n') and b'Content-Length: 3' in first
    S.write_frame('a',key,b'new')
    assert (await anext(gen)).endswith(b'new\r\n')
    await gen.aclose()

@pytest.mark.asyncio
async def test_dead_producer_does_not_leave_live_looking_frame(root):
    key='b'*32;S.write_frame('a',key,b'old')
    os.utime(S.frame_path('a',key),(time.time()-31,)*2)
    async def connected():return False
    assert [x async for x in S.frames('a',key,connected)] == []

@pytest.mark.asyncio
async def test_page_change_closes_previous_stream(root,monkeypatch):
    monkeypatch.setenv('DAN_TOOL_HOST','1');monkeypatch.setenv('DAN_SESSION_ID','a')
    class CDP:
        def __init__(self):self.commands=[]
        def on(self,*args):pass
        async def send(self,name,*args):self.commands.append(name)
        async def detach(self):pass
    class Page:
        context=None
        def __init__(self):self.context=self;self.cdp=CDP()
        async def new_cdp_session(self,p):return self.cdp
        def is_closed(self):return False
    state={};first=Page();second=Page()
    await S.follow_browser(state,first);previous=state['voice_stream']
    await previous.on_frame({'data':'eA==','sessionId':1})
    assert S.current_url(state).endswith('.mjpeg')
    await S.follow_browser(state,second)
    assert previous.closed and 'Page.stopScreencast' in first.cdp.commands
    assert not S.frame_path('a',previous.key).exists()
    await state['voice_stream'].close()

@pytest.mark.asyncio
async def test_real_cdp_sends_frames_during_smooth_scroll(root):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page()
        await page.set_content('<style>body{height:5000px;background:linear-gradient(red,blue)}</style><h1>Actual scrolling</h1>')
        stream=await S.BrowserStream('test').start(page)
        try:
            for _ in range(40):
                if stream.data:break
                await asyncio.sleep(.05)
            assert stream.data
            frames={stream.data}
            await page.evaluate('window.scrollTo({top:1800,behavior:"smooth"})')
            for _ in range(30):
                await asyncio.sleep(.05);frames.add(stream.data)
            assert len(frames)>=4, len(frames)
        finally:
            await stream.close();await browser.close()

@pytest.mark.asyncio
async def test_stream_route_requires_auth_and_room_ownership(root, monkeypatch):
    from types import SimpleNamespace
    from starlette.requests import Request
    from fastapi import HTTPException
    from app.api import voicelog_routes as routes
    request = Request({'type':'http', 'headers':[], 'method':'GET', 'path':'/'})
    key = 'c'*32
    S.write_frame('a',key,b'jpeg')
    with pytest.raises(HTTPException) as error:
        await routes.call_screen_image('a', key+'.mjpeg', request)
    assert error.value.status_code == 401
    monkeypatch.setattr(routes, '_get_user', lambda request: SimpleNamespace(user_id='owner'))
    class Chat:
        async def get_room(self, room, owner): return room == 'a'
    monkeypatch.setattr(routes, 'ChatService', Chat)
    with pytest.raises(HTTPException) as error:
        await routes.call_screen_image('b',key+'.mjpeg',request)
    assert error.value.status_code == 403
    response = await routes.call_screen_image('a',key+'.mjpeg',request)
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.media_type.startswith('multipart/')
