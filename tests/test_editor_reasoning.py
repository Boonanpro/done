import asyncio
import json
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import editor_assistant_routes as api
from app.services import editor_reasoning as reasoning, timeline_draft as td

@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setattr(td,'UPLOAD_ROOT',tmp_path)
    monkeypatch.setattr(api,'_get_user',lambda _:SimpleNamespace(user_id='owner'))
    folder=tmp_path/'room';folder.mkdir();(folder/'contents.json').write_text('[]');(folder/'assets.json').write_text('[]')
    cid=api.new_content(None,api.NewContent(room_id='room'))['content_id']
    begun=api.begin(None,api.Context(room_id='room',content_id=cid,utterance='Google直結で1ドル以内なら作って。Higgsfieldは使わない。'))
    app=FastAPI();app.include_router(api.router)
    return TestClient(app),cid,begun

def test_stream_keeps_raw_input_and_continues_tool_result(env,monkeypatch):
    client,cid,b=env;seen=[]
    async def stream(inputs,tools):
        seen.append(json.loads(json.dumps(inputs)))
        if len(seen)==1:
            yield {'type':'text','delta':'料金を確認して進めます。'}
            yield {'type':'completed','output':[{'type':'function_call','name':'execute_work','arguments':'{}','call_id':'call_1'}],'usage':None}
        else:
            yield {'type':'text','delta':'依頼を受け付けました。'}
            yield {'type':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'依頼を受け付けました。'}]}],'usage':None}
    monkeypatch.setattr(reasoning,'stream_response',stream)
    body={'room_id':'room','turn_id':b['turn_id']}
    r=client.post('/editor-assistant/reason',json=body)
    events=[json.loads(l) for l in r.text.splitlines()]
    assert [e['type'] for e in events]==['text','tool','done']
    assert any('Google直結で1ドル以内なら作って' in str(i) for i in seen[0])
    invalid=client.post('/editor-assistant/reason',json={**body,'outputs':[{'call_id':'wrong','result':{}}]})
    assert 'error' in invalid.text and len(seen)==1
    r=client.post('/editor-assistant/reason',json={**body,'outputs':[{'call_id':'call_1','result':{'ok':True,'job_id':'j'}}]})
    assert '依頼を受け付けました' in r.text
    assert seen[1][-1]['type']=='function_call_output'
    assert json.loads(seen[1][-1]['output'])['job_id']=='j'

def test_canceled_turn_never_calls_model(env,monkeypatch):
    client,cid,b=env
    client.post('/editor-assistant/cancel',json={'room_id':'room','turn_id':b['turn_id'],'name':'cancel'})
    r=client.post('/editor-assistant/reason',json={'room_id':'room','turn_id':b['turn_id']})
    assert r.status_code==409

def test_execute_work_has_no_preparation_switch_and_keeps_original(env,monkeypatch):
    client,cid,b=env
    from app.api import production_asset_routes as production
    captured=[]
    async def create(body,bg,user):
        captured.append(body);return {'id':'fixture-job'}
    monkeypatch.setattr(production,'create_job',create)
    r=client.post('/editor-assistant/tool',json={'room_id':'room','turn_id':b['turn_id'],'name':'execute_work','args':{'task_kind':'prepare'}})
    assert r.status_code==200 and r.json()['job_id']=='fixture-job'
    assert captured[0].instruction['preparation_only'] is False
    text=captured[0].instruction['revision_text']
    assert 'Google直結で1ドル以内なら作って' in text and 'Higgsfieldは使わない' in text
    tool=next(t for t in reasoning.tools_for_conversation(api.EDITOR_TOOLS) if t['name']=='execute_work')
    assert 'task_kind' not in tool['parameters']['properties']

def test_reply_history_preserves_assistant_suggestion_as_assistant():
    messages=reasoning.initial_input({'utterance':'人物なしとは決めてない'},[
        {'role':'assistant','text':'人物なしにしますか？'},{'role':'user','text':'人物なしとは決めてない'}])
    assert messages[-2]['role']=='assistant'
    assert len([m for m in messages if m.get('content')=='人物なしとは決めてない'])==1


def test_progress_does_not_validate_unrelated_nullable_pointer(env, monkeypatch):
    client, cid, _ = env
    monkeypatch.setattr(api.project, 'status', lambda *_: {'jobs': []})
    r = client.post('/editor-assistant/project-status', json={
        'room_id': 'room', 'content_id': cid, 'pointer': None, 'reference_focus': {'id': 'ref'}})
    assert r.status_code == 200


def test_notification_reads_latest_agreement_even_with_old_question(env, monkeypatch):
    client, cid, _ = env; seen = []
    monkeypatch.setattr(api.project, 'status', lambda *_: {'jobs': [
        {'id': 'j', 'status': 'done', 'question': {'text': 'Buy subscription?'}, 'result': {'committed': True}}]})
    monkeypatch.setattr(api.project, 'dialogue', lambda *_: {'messages': [{'role': 'user', 'text': '下書きが先。課金は後。'}]})
    async def stream(inputs, tools):
        seen.extend(inputs); yield {'type': 'text', 'delta': '下書きを保存しました。'}
    monkeypatch.setattr(reasoning, 'stream_response', stream)
    assert client.post('/editor-assistant/notice', json={'room_id': 'room', 'content_id': cid, 'job_id': 'j'}).status_code == 200
    assert any(i['content'] == '下書きが先。課金は後。' for i in seen)
