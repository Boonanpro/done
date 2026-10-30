import asyncio
import json
from types import SimpleNamespace
import pytest
from app.services import voice_screen as C, voice_stage as S
from app.services.voice_sideband import Dialogue
from app.services.voice_stage_cue import clean, from_words

@pytest.fixture
def stage(tmp_path, monkeypatch):
    monkeypatch.setattr(C,'ROOT',tmp_path); monkeypatch.setattr(S,'ROOT',tmp_path)
    s=S.Stage('test-room','session',Dialogue(),lambda *a,**kw:None)
    s._apply('test',frame='/preview/test')
    yield s
    s.close()

def observation(stage, risk='navigate', value='hello', client='one'):
    return {'view_id':stage.view_id,'session_id':stage.session_id,'client_id':client,'screen':{'page_id':'page','url':'/artifacts/test?call=1','title':'試験用画面','text':'試験用',
      'controls':[{'id':'c1','name':'確認','role':'button','risk':risk,'fingerprint':'observed','value':value}]}}

@pytest.mark.asyncio
async def test_receipt_after_command_and_no_permission_flag_from_model(stage):
    assert C.accept(stage.room_id,stage.state(),observation(stage))
    async def receive():
        while not stage.command: await asyncio.sleep(.001)
        command=stage.command['screen_command']
        assert not command['authorized']
        body=observation(stage);body['receipt']={'request_id':command['request_id'],'result':{'ok':True,'dispatched':True}}
        C.accept(stage.room_id,stage.state(),body)
    receiver=asyncio.create_task(receive())
    out=await C.operate(stage,'click','c1',page_id='page',fingerprint='observed')
    await receiver
    assert out['ok'] and out['dispatched']

@pytest.mark.asyncio
async def test_readback_then_actual_user_approval_and_single_use(stage):
    C.accept(stage.room_id,stage.state(),observation(stage,'confirm'))
    stage.dialogue.add('user','送って')
    out=await C.operate(stage,'click','c1',page_id='page',fingerprint='observed'); assert out['requires_approval'] and stage.command is None
    stage.dialogue.add('assistant',out['read_back']);stage.dialogue.add('user','まだ送らないで')
    assert (await C.operate(stage,'click','c1',page_id='page',fingerprint='observed'))['requires_approval']
    stage.dialogue.add('assistant',out['read_back']);stage.dialogue.add('user','いいよ')
    async def receive():
        while not stage.command: await asyncio.sleep(.001)
        cmd=stage.command['screen_command'];assert cmd['authorized']
        body=observation(stage,'confirm');body['receipt']={'request_id':cmd['request_id'],'result':{'ok':True,'dispatched':True}}
        C.accept(stage.room_id,stage.state(),body)
    receiver=asyncio.create_task(receive())
    assert (await C.operate(stage,'click','c1',page_id='page',fingerprint='observed'))['ok'];await receiver
    assert (await C.operate(stage,'click','c1',page_id='page',fingerprint='observed'))['requires_approval']

@pytest.mark.asyncio
async def test_changed_form_invalidates_spoken_approval(stage):
    C.accept(stage.room_id,stage.state(),observation(stage,'confirm'))
    out=await C.operate(stage,'click','c1',page_id='page',fingerprint='observed')
    stage.dialogue.add('assistant',out['read_back']);stage.dialogue.add('user','いいよ')
    C.accept(stage.room_id,stage.state(),observation(stage,'confirm',value='different recipient'))
    assert not (await C.operate(stage,'click','c1',page_id='page',fingerprint='observed'))['ok']
    assert stage.command is None

@pytest.mark.asyncio
async def test_other_device_old_session_wrong_site_and_receipt_persistence(stage):
    body=observation(stage);body['receipt']={'request_id':'one','result':{'ok':True}}
    assert C.accept(stage.room_id,stage.state(),body)
    assert not C.accept(stage.room_id,stage.state(),observation(stage,client='two'))
    old=observation(stage);old['session_id']='previous'
    assert not C.accept(stage.room_id,stage.state(),old)
    wrong=observation(stage);wrong['screen']['url']='/artifacts/elsewhere'
    assert not C.accept(stage.room_id,stage.state(),wrong)
    assert C.accept(stage.room_id,stage.state(),observation(stage))
    assert C.read(stage.room_id)['receipt']['request_id']=='one'
    stage.frame='/preview/elsewhere';assert not C.inspect(stage)['ok']

@pytest.mark.parametrize('text,code', [('確認番号は四八三九二〇です。','483920'),('認証コードは０１２３４５です','012345'),('認証コードは千二百です',None),('確認番号は12です',None)])
def test_cue_codes(text,code):
    out=from_words(text)
    assert (out or {}).get('value')==code

@pytest.mark.asyncio
async def test_code_renders_without_model_call_and_does_not_replace_real_screen(stage):
    stage._apply('',program='root = Stat("合計", 3)')
    stage.heard('assistant','確認番号は四八三九二〇です。')
    assert stage.state()['cue']['value']=='483920'
    stage._apply('test',frame='/preview/test')
    stage.heard('assistant','確認番号は一二三四五六です。')
    assert stage.frame and stage.cue is None

@pytest.mark.asyncio
async def test_api_auth_scope_and_session(monkeypatch,stage):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import voicelog_routes as R
    app=FastAPI();app.include_router(R.router)
    client=TestClient(app)
    body=observation(stage)
    assert client.post('/voicelog/stage/test-room/screen',json=body).status_code==401
    monkeypatch.setattr(R,'_get_user',lambda _:SimpleNamespace(user_id='owner'))
    class Chats:
        async def get_room(self,*_): return None
    monkeypatch.setattr(R,'ChatService',Chats)
    assert client.post('/voicelog/stage/test-room/screen',json=body).status_code==403
    async def owned(*_): return {'id':'test-room'}
    monkeypatch.setattr(Chats,'get_room',owned)
    assert client.post('/voicelog/stage/test-room/screen',json=body).json()['accepted']

@pytest.mark.asyncio
async def test_old_page_id_and_changed_target_rejected_before_command(stage):
    C.accept(stage.room_id,stage.state(),observation(stage))
    assert not (await C.operate(stage,'click','c1',page_id='previous',fingerprint='observed'))['ok']
    assert not (await C.operate(stage,'click','c1',page_id='page',fingerprint='changed'))['ok']
    assert stage.command is None


def test_screens_are_room_private_not_shared_uploads(tmp_path,monkeypatch):
    from app.services import voice_screen_media as M
    from app.services.tool_host import screen_image
    import base64
    monkeypatch.setattr(M,'ROOT',tmp_path)
    monkeypatch.setenv('DAN_SESSION_ID','private-room')
    image=SimpleNamespace(type='image',mimeType='image/png',data=base64.b64encode(b'test-png').decode())
    url=screen_image([image],'browser',{'action':'screenshot'})
    assert M.URL.fullmatch(url) and '/files/' not in url
    assert (M.directory('private-room')/url.rsplit('/',1)[-1]).read_bytes()==b'test-png'
    assert screen_image([image],'read_url',{})==''
    assert S.safe_image(url)==url

@pytest.mark.asyncio
async def test_same_site_different_document_does_not_reuse_old_snapshot(stage):
    body=observation(stage)
    assert C.accept(stage.room_id,stage.state(),body)
    stage._apply('another document',frame='/preview/test?document=2')
    assert not C.current(stage)
    assert not C.accept(stage.room_id,stage.state(),body)
