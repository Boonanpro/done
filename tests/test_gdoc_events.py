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


def export_comment(text='導入を台本にしてください', date='2026-11-01T13:30:46Z', ident='14'):
    return {'id':ident,'author_label':'本人','date':date,'text':text}


def test_suggestion_reply_enters_same_inbox_once_despite_docx_renumbering(store):
    old=export_comment('以前のコメント', '2026-10-30T12:00:00Z','1')
    new=export_comment()
    payload={'export_comments':[old,new], 'threads':[], 'paragraphs':[
        {'before':'旧導入','after':'新導入','comment_refs':['14']}]}
    changes=E.ingest_export_comments('file',payload,[old])
    assert len(changes)==1 and changes[0]['new'][0]['content']==new['text']
    assert changes[0]['requires_browser_verification']
    assert changes[0]['context'][0]['after']=='新導入'
    new['id']='25'
    assert E.ingest_export_comments('file',payload,[old])==[]
    new['text']='導入は1本目からの続きにしてください'
    assert len(E.ingest_export_comments('file',payload,[old]))==1
    with E.db() as c: assert c.execute('SELECT count(*) FROM batches').fetchone()[0]==2


def test_export_ignores_drive_duplicates_and_dan_but_requires_author_verification(store):
    normal=export_comment('普通の質問')
    dan=export_comment('ダン：直しました','2026-11-01T13:31:00Z')
    unknown=export_comment('書き直して','2026-11-01T13:32:00Z')
    unknown['author_label']='別の人'
    changes=E.ingest_export_comments('file', {'export_comments':[normal,dan,unknown],
        'threads':[thread('普通の質問')]})
    assert len(changes)==1 and changes[0]['thread']['author_label']=='別の人'
    assert changes[0]['requires_browser_verification'] is True
    doc={'file_id':'file','room_id':'room'}
    prompt=E.prompt(doc,{'id':'batch','payload':json.dumps(changes)})
    assert '第三者・作者不明なら本文変更も返信もせず' in prompt
    assert 'confirm-export-reply' in prompt


def test_export_receipt_checks_current_source_and_saved_reply_without_send(store,monkeypatch):
    from app.services import gdoc_drive, script_learning
    source=export_comment()
    changes=E.ingest_export_comments('file',{'export_comments':[source]})
    with E.db() as c: b=dict(c.execute('SELECT * FROM batches').fetchone())
    monkeypatch.setattr(gdoc_drive,'export_docx',lambda *args:b'export')
    items=[source]
    monkeypatch.setattr(script_learning,'parse_docx',lambda _: {'export_comments':items})
    with pytest.raises(ValueError,match='not uniquely'): E.confirm_export_reply(b['id'],changes[0]['comment_id'],'ダン：直しました')
    items.append(export_comment('ダン：直しました','2026-11-01T14:00:00Z'))
    assert E.confirm_export_reply(b['id'],changes[0]['comment_id'],'ダン：直しました')['verified_export']
    assert E.confirm_export_reply(b['id'],changes[0]['comment_id'],'ダン：直しました')['verified_export']
    source['text']='最新の訂正'
    with pytest.raises(ValueError,match='changed'): E.confirm_export_reply(b['id'],changes[0]['comment_id'],'ダン：直しました')


def test_comment_from_owner_other_account_counts_only_on_owner_only_document(store):
    other = thread('担当コーチの段は？', author={'displayName':'投手コーチイツキ','me':False})
    with E.db() as c:
        assert not E.ingest(c,'file',[other])
        other['content'] = '担当コーチの段は書いてる？'
        assert E.ingest(c,'file',[other],owner_only=True)[0]['new'][0]['content'] == '担当コーチの段は書いてる？'


def test_owner_only_requires_every_permission_to_be_an_owner_account(monkeypatch):
    from app.services import gdoc_drive
    perms = {'permissions':[{'type':'user','emailAddress':'shub6923@gmail.com'},
                            {'type':'user','emailAddress':'0aw325171@gmail.com'}]}
    monkeypatch.setattr(gdoc_drive,'request',lambda *a,**k: perms)
    assert E.owner_only('test','file')
    perms['permissions'].append({'type':'anyone'})
    assert not E.owner_only('test','file')
    perms['permissions'][-1] = {'type':'user','emailAddress':'client@example.com'}
    assert not E.owner_only('test','file')
    monkeypatch.setattr(gdoc_drive,'request',lambda *a,**k: (_ for _ in ()).throw(RuntimeError()))
    assert not E.owner_only('test','file')


def test_mail_notice_for_registered_document_marks_dirty_without_chat(store):
    assert E.take_mail_notice('file','room')
    with E.db() as c: assert c.execute('SELECT dirty FROM docs').fetchone()[0] == 1
    assert (store/'wake').exists()


def test_mail_notice_registers_unknown_document_and_keeps_the_announced_comment(store, monkeypatch):
    from app.services import gdoc_drive
    registered = []
    monkeypatch.setattr(E,'accounts',lambda: ['nope','test'])
    def request(account,method,path,body=None,params=None):
        if account=='nope': raise RuntimeError('no access')
        return {'capabilities':{'canComment':True}}
    monkeypatch.setattr(gdoc_drive,'request',request)
    monkeypatch.setattr(E,'register',lambda f,r,a,fresh_since=None: registered.append((f,r,a,fresh_since)))
    assert E.take_mail_notice('newfile','room',received=1793600000)
    assert registered == [('newfile','room','test',E.iso(1793600000-600))]
    with E.db() as c:
        old = thread('前からある指示', createdTime='2026-11-01T00:00:00Z')
        new = {**thread('今の指示', createdTime='2026-11-02T06:24:00Z'), 'id':'c2'}
        changes = E.ingest(c,'file2',[old,new],baseline=True,fresh_since='2026-11-02T06:14:35Z')
        assert [x['comment_id'] for x in changes] == ['c2']


def test_docs_comment_mail_does_not_wake_the_chat(monkeypatch):
    from app.services import inbound_wakeup as W
    from app.services import gdoc_events
    taken = []
    monkeypatch.setattr(gdoc_events,'take_mail_notice',lambda f,r,t=None: taken.append((f,r)) or True)
    msg = {'user_id':'u','source':'gmail','subject':'台本',
           'sender_info':{'from':'投手コーチイツキ (Google ドキュメント) <comments-noreply@docs.google.com>',
                          'date':'Sun, 01 Nov 2026 22:24:35 -0800'},
           'content':'（https://docs.google.com/document/d/1XLLtHr2XY9bFEnrxrUaL4yaENs2gGTJ2Y8hGzmNbjqc/edit?usp=comment_email_document）'}
    assert W.schedule_room_wakeup(msg,'room',reason='content:existing')   # no running loop: would be False if it woke
    assert taken == [('1XLLtHr2XY9bFEnrxrUaL4yaENs2gGTJ2Y8hGzmNbjqc','room')]
    assert W.docs_comment_file({**msg,'sender_info':{'from':'someone@example.com'}}) is None


def test_split_comment_waits_for_the_owner_and_runs_as_one(store):
    first = {'comment_id':'c1','new':[{'id':'c:c1','revision':'a','content':'前半'}],'thread':{'id':'c1'}}
    second = {'comment_id':'c1','new':[{'id':'r:r1','revision':'b','content':'後半の質問'}],'thread':{'id':'c1','replies':[{'id':'r1'}]}}
    now = time.time()
    with E.db() as c:
        c.execute('INSERT INTO batches(id,file_id,payload,created) VALUES(?,?,?,?)',('b1','file',json.dumps([first]),E.iso(now-20)))
        c.execute('INSERT INTO batches(id,file_id,payload,created) VALUES(?,?,?,?)',('b2','file',json.dumps([second]),E.iso(now-5)))
    batch, wait = E.next_batch('file', now)
    assert batch is None and wait > now
    batch, wait = E.next_batch('file', now+60)
    assert batch['id'] == 'b1' and not wait
    payload = json.loads(batch['payload'])
    assert len(payload) == 1 and [x['content'] for x in payload[0]['new']] == ['前半','後半の質問']
    with E.db() as c: assert c.execute("SELECT status FROM batches WHERE id='b2'").fetchone()[0] == 'merged'
    assert '発言ごと' in E.prompt({'file_id':'file','room_id':'room'}, dict(batch))


def test_dan_reason_notes_do_not_wake(store):
    with E.db() as c:
        assert not E.ingest(c, 'file', [thread('【変えた所】1文足しました。\n【根拠】えるさん')])
        assert E.ingest(c, 'file', [thread('ここ直して', id='c2')])

def test_fresh_window_ignores_dan_on_new_document(store):
    mine = {'id':'c1','content':'理由のメモ','author':{'me':True},'createdTime':'2026-11-10T07:05:00Z',
            'replies':[{'id':'r1','content':'先ず否定する答えを変えて','author':{'me':False},
                        'createdTime':'2026-11-10T07:16:00Z'}]}
    with E.db() as c:
        got = E.ingest(c, 'new', [mine], baseline=True, owner_only=True,
                       fresh_since='2026-11-10T07:00:00Z', fresh_mine=False)
    assert [n['id'] for n in got[0]['new']] == ['r:r1']

def test_adopt_registers_a_private_document_shown_in_a_room(store, monkeypatch):
    import app.services.gdoc_drive as D
    monkeypatch.setattr(E, 'accounts', lambda: ['shub'])
    monkeypatch.setattr(D, 'request', lambda *a, **k: {'files':[{'id':'file'},{'id':'new'},{'id':'shared'},{'id':'stray'}]})
    monkeypatch.setattr(E, 'room_for_file', lambda f: {'new':'room','shared':'room'}.get(f))
    monkeypatch.setattr(E, 'owner_only', lambda a, f: f == 'new')
    calls = []
    def register(*a, **k):
        calls.append((a, k))
        with E.db() as c:
            c.execute('INSERT INTO docs(file_id,room_id,account) VALUES(?,?,?)', (a[0], a[1], a[2]))
    monkeypatch.setattr(E, 'register', register)
    E._adopt_seen.clear()
    assert E.adopt_new_docs(now=1000.0) == ['new']
    assert calls[0][0] == ('new', 'room', 'shub') and calls[0][1]['fresh_mine'] is False
    assert E.adopt_new_docs(now=1100.0) == []                 # not-ready ones wait before a recheck
    assert set(E._adopt_seen) == {'shared', 'stray'}

def test_documents_settle_quickly(store):
    assert E.SETTLE <= 20
