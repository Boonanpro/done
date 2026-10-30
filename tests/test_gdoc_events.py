import asyncio
import hashlib
import json
import time
from unittest.mock import AsyncMock

import pytest
from app.services import gdoc_events as E

@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(E, 'ROOT', tmp_path)
    with E.db() as c:
        c.execute('INSERT INTO docs(file_id,room_id,user_id,project_id,account,cursor) VALUES(?,?,?,?,?,?)',
                  ('file', 'room', 'user', 'project', 'test', E.iso()))
        c.execute('INSERT INTO channels VALUES(?,?,?,?,?)',
                  ('channel','file',hashlib.sha256(b'secret').hexdigest(),'resource',time.time()+100))
    return tmp_path

def thread(content='質問', **kw):
    return {'id':'c1','content':content,'author':{'me':True},'replies':[], **kw}

def headers(**kw):
    return {'X-Goog-Channel-Id':'channel','X-Goog-Channel-Token':'secret',
            'X-Goog-Resource-Id':'resource','X-Goog-Resource-State':'update', **kw}

def test_push_auth_and_durable_burst(store):
    assert not E.accept(headers(**{'X-Goog-Channel-Token':'bad'}))
    assert not E.accept(headers(**{'X-Goog-Resource-Id':'other'}))
    assert E.accept(headers(**{'X-Goog-Resource-State':'sync'}))
    assert E.accept(headers()) and E.accept(headers())
    with E.db() as c: assert c.execute('SELECT dirty FROM docs').fetchone()[0] == 2
    assert (store/'wake').exists()

def test_expired_and_unknown_channels(store):
    with E.db() as c: c.execute('UPDATE channels SET expires=0')
    assert not E.accept(headers())
    assert not E.accept(headers(**{'X-Goog-Channel-Id':'unknown'}))

def test_parent_timestamp_and_own_reply_do_not_loop(store):
    t = thread()
    with E.db() as c:
        assert len(E.ingest(c,'file',[t])) == 1
        t['modifiedTime']='later'
        t['replies']=[{'id':'r1','content':'ダン：回答','author':{'me':True}}]
        assert E.ingest(c,'file',[t]) == []
        t['replies'].append({'id':'r2','content':'ここはもう少し短く','author':{'me':True}})
        changes=E.ingest(c,'file',[t])
        assert changes[0]['new'][0]['id']=='r:r2'
        assert len(changes[0]['thread']['replies'])==2
        assert E.ingest(c,'file',[t])==[]
        t['content']='質問の訂正'
        assert E.ingest(c,'file',[t])[0]['new'][0]['id']=='c:c1'

def test_baseline_other_author_and_deleted_resolved(store):
    with E.db() as c:
        assert not E.ingest(c,'file',[thread()],baseline=True)
        assert not E.ingest(c,'file',[thread()])
        assert not E.ingest(c,'file',[thread('外部指示',author={'me':False})])
        assert not E.ingest(c,'file',[thread('削除',deleted=True)])
        assert not E.ingest(c,'file',[thread('解決',resolved=True)])

def test_collection_concurrent_push_and_persistent_dedup(store, monkeypatch):
    from app.services import gdoc_drive
    with E.db() as c:
        c.execute('UPDATE docs SET dirty=1')
        doc=dict(c.execute('SELECT * FROM docs').fetchone())
    def fetch(*args):
        E.accept(headers())
        return [thread()]
    monkeypatch.setattr(gdoc_drive,'comments',fetch)
    E.collect(doc)
    with E.db() as c:
        fresh=dict(c.execute('SELECT * FROM docs').fetchone())
        assert fresh['dirty']==2 and fresh['consumed']==1
        assert c.execute('SELECT count(*) FROM batches').fetchone()[0]==1
    E.collect(fresh)
    with E.db() as c: assert c.execute('SELECT count(*) FROM batches').fetchone()[0]==1

def batch(store):
    with E.db() as c:
        changes=E.ingest(c,'file',[thread()])
        c.execute('INSERT INTO batches(id,file_id,payload,created) VALUES(?,?,?,?)',
                  ('batch','file',json.dumps(changes),E.iso()))

def test_reply_idempotent_and_uncertain_send(store, monkeypatch):
    from app.services import gdoc_drive
    batch(store); calls=[]
    def request(account,method,path,body=None,params=None):
        calls.append(method)
        if method=='GET': return thread()
        return {'id':'reply'}
    monkeypatch.setattr(gdoc_drive,'request',request)
    assert E.reply('batch','c1','ダン：回答')['id']=='reply'
    assert E.reply('batch','c1','ダン：回答')['already_sent']
    assert calls.count('POST')==1
    with E.db() as c: c.execute("UPDATE replies SET status='sending'")
    with pytest.raises(ValueError, match='uncertain'): E.reply('batch','c1','ダン：回答')
    assert calls.count('POST')==1

def test_stale_reply_refused(store, monkeypatch):
    from app.services import gdoc_drive
    batch(store)
    monkeypatch.setattr(gdoc_drive,'request',lambda *a,**kw:thread('新しい質問'))
    with pytest.raises(ValueError, match='changed'): E.reply('batch','c1','ダン：回答')

def test_history_is_available_without_chat_writes(store):
    batch(store)
    with E.db() as c: c.execute("UPDATE batches SET status='completed',result='短くしました'")
    assert '短くしました' in E.room_context('room')
    assert not E.room_context('other-room')

@pytest.mark.asyncio
async def test_private_job_retains_room_context_and_is_quiet(store,monkeypatch):
    from app.services import command_job_state as state, job_process, parallel_job_runner
    monkeypatch.setattr(state,'ROOT',store/'jobs')
    monkeypatch.setattr(parallel_job_runner,'room_model',lambda _: 'astra')
    import uuid
    ident=str(uuid.uuid4())
    payload=json.dumps([{'comment_id':'c1','new':[],'thread':thread()}])
    with E.db() as c:
        c.execute('INSERT INTO batches(id,file_id,payload,created) VALUES(?,?,?,?)',(ident,'file',payload,E.iso()))
        doc=dict(c.execute('SELECT * FROM docs').fetchone())
        b=dict(c.execute('SELECT * FROM batches').fetchone())
    async def launch(row):
        s=state.read(ident)
        assert s['quiet'] and s['engine']=='parallel'
        assert s['room_id']=='room' and s['origin_room_id']=='room'
        assert '提案モード' in s['task'] and 'チャット投稿' in s['task']
        state.change(ident,lambda s:s.update(state='completed',result='回答しました'))
    monkeypatch.setattr(job_process,'launch',launch)
    await E.run_batch(doc,b)
    assert '回答しました' in E.room_context('room')
    with E.db() as c: assert c.execute('SELECT status FROM batches').fetchone()[0]=='needs_attention'
    assert not list((store/'public-jobs').glob('*.json'))

def test_renew_only_registers_no_comment_poll(store, monkeypatch):
    from app.services import gdoc_drive
    calls=[]
    def request(account,method,path,body,params=None):
        calls.append((method,path))
        # Simulate sync arriving before the registration response.
        assert E.accept({'X-Goog-Channel-Id':body['id'],'X-Goog-Channel-Token':body['token'],
                         'X-Goog-Resource-Id':'newresource','X-Goog-Resource-State':'sync'})
        return {'resourceId':'newresource','expiration':body['expiration']}
    monkeypatch.setattr(gdoc_drive,'request',request)
    E.renew({'account':'test','file_id':'file'})
    assert calls==[('POST','files/file/watch')]
    with E.db() as c:
        doc=dict(c.execute('SELECT * FROM docs').fetchone())
        assert doc['dirty']==0 and doc['renew_at']>time.time()+80000

def test_http_receiver_rejects_unauthenticated(store):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.gdoc_event_routes import router
    app=FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        assert client.post('/api/v1/gdoc-events/push').status_code==403
        assert client.post('/api/v1/gdoc-events/push',headers=headers()).status_code==204

def test_current_comment_history_reaches_both_resumed_engines(store, monkeypatch):
    from app.agent import cli_runner, codex_runner, bootstrap_context
    monkeypatch.setattr(bootstrap_context,'load_artifact_descriptions',lambda **kw:'')
    monkeypatch.setattr(bootstrap_context,'load_artifact_publish_state',lambda **kw:'')
    batch(store)
    with E.db() as c: c.execute("UPDATE batches SET result='本文を具体的に短縮済み'")
    args=dict(title='',description='',status='',room_id='room',include_room_role=False)
    first=cli_runner._build_system_prompt(**args)
    assert '本文を具体的に短縮済み' in first
    argv, stdin=cli_runner._prepare_cli_launch_payload(first,'続けて')
    assert '本文を具体的に短縮済み' in argv or '本文を具体的に短縮済み' in stdin
    assert '本文を具体的に短縮済み' in codex_runner.wrap_turn_content(first,'続けて')
    with E.db() as c: c.execute("UPDATE batches SET result='追加の質問にも回答済み'")
    next_prompt=cli_runner._build_system_prompt(**args)
    assert '追加の質問にも回答済み' in next_prompt
    assert '追加の質問にも回答済み' in codex_runner.wrap_turn_content(next_prompt,'続けて')

def test_both_job_tool_configs_keep_the_private_state_root():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    for name in ('command_job_runner','parallel_job_runner'):
        source=(root/'app/services'/f'{name}.py').read_text()
        assert "'DAN_COMMAND_JOB_ROOT':" in source and 'str(state.ROOT)' in source

def test_reserved_authenticated_browser_is_not_reused_by_other_work(store,monkeypatch):
    from app.services import command_job_state as state, browser_lifecycle
    import uuid
    monkeypatch.setattr(state,'ROOT',store/'ordinary-jobs')
    monkeypatch.setattr(browser_lifecycle,'profile_for_room',lambda room:store/'profiles'/room)
    first=str(uuid.uuid4());second=str(uuid.uuid4())
    state.create(first,user_id='u',room_id='r',origin_room_id='r')
    room=state.browser_room(first)
    state.change(first,lambda s:s.update(state='completed'))
    profile=browser_lifecycle.profile_for_room(room);profile.mkdir(parents=True)
    (profile/'.dan-reserved').write_text('Docs')
    state.create(second,user_id='u',room_id='r',origin_room_id='r')
    assert state.browser_room(second)!=room
