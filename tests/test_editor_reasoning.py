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
    async def stream(inputs,tools,**kwargs):
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
    assert text.count('Google直結で1ドル以内なら作って') == 1
    tool=next(t for t in reasoning.tools_for_conversation(api.EDITOR_TOOLS) if t['name']=='execute_work')
    assert 'task_kind' not in tool['parameters']['properties']

def test_reply_history_preserves_assistant_suggestion_as_assistant():
    messages=reasoning.initial_input({'utterance':'人物なしとは決めてない'},[
        {'role':'assistant','text':'人物なしにしますか？'},{'role':'user','text':'人物なしとは決めてない'}])
    assert messages[-2]['role']=='assistant'
    assert len([m for m in messages if m.get('content')=='人物なしとは決めてない'])==1


def test_old_screen_traces_are_not_repeated_but_all_speech_is_preserved():
    rows=[{'role':'user','text':'old','observed_views':[{'view':{'content_id':'old-scene'}}]},
          {'role':'assistant','text':'suggestion'},
          {'role':'user','text':'new','observed_views':[{'view':{'content_id':'new-scene'}}]}]
    inputs=reasoning.initial_input({'live_dialogue':rows},[])
    encoded=json.dumps(inputs)
    assert 'old-scene' not in encoded and 'new-scene' in encoded
    assert [r['content'] for r in inputs if r['role'] in ('user','assistant')]==['old','suggestion','new']


def test_separate_sample_needs_no_timeline_selection(env,monkeypatch):
    client,cid,_=env
    from app.api import production_asset_routes as production
    from app.services import timeline_agent
    monkeypatch.setattr(timeline_agent,'content_busy',lambda _:None)
    captured=[]
    async def create(body,bg,user):
        captured.append(body);return {'id':'sample-job'}
    monkeypatch.setattr(production,'create_job',create)
    contents=td._read_contents_raw('room')
    content=td._find_content(contents,cid)
    seq=td._content_sequence(content)
    seq['tracks']=[{'id':'v1','type':'video','clips':[{'id':'existing','timeline_start':0,'timeline_end':5,'type':'text','text':'keep'}]}]
    td._write_contents_raw('room',contents)
    b=api.begin(None,api.Context(room_id='room',content_id=cid,input_mode='voice',utterance='別に15秒の見本を見せて'))
    body={'room_id':'room','turn_id':b['turn_id'],'name':'execute_work'}
    # An unspecified edit still cannot overwrite an unselected timeline.
    assert client.post('/editor-assistant/tool',json={**body,'args':{}}).json()['ok'] is False
    r=client.post('/editor-assistant/tool',json={**body,'args':{'destination':'presentation'}}).json()
    assert r['ok'] and r['job_id']=='sample-job'
    instruction=captured[0].instruction
    assert instruction['presentation_only'] is True
    assert instruction['preparation_only'] is False
    assert instruction['selected_clips']==[]
    assert '15秒の見本' in instruction['revision_text']


def test_sample_draft_cannot_commit_even_if_scope_is_changed(env):
    _,cid,_=env
    draft=td.create_draft('room',cid,'sample')
    draft['presentation_only']=True
    draft['edit_scope']=None
    td.save_draft(draft)
    result=td.commit_draft('room',draft['draft_id'],lambda *_:[])
    assert not result['ok']


def test_read_skill_resolves_installed_skill_and_reports_missing(env,monkeypatch,tmp_path):
    client,_,b=env
    from app.agent.v2.tools import SkillRegistry
    monkeypatch.setattr(SkillRegistry,'get_prompt',lambda _: '')
    monkeypatch.setattr(api.Path,'home',classmethod(lambda _:tmp_path))
    p=tmp_path/'.agents/skills/example/SKILL.md';p.parent.mkdir(parents=True);p.write_text('specific domain knowledge',encoding='utf8')
    body={'room_id':'room','turn_id':b['turn_id'],'name':'read_skill'}
    result=client.post('/editor-assistant/tool',json={**body,'args':{'name':'example'}}).json()
    assert result['text']=='specific domain knowledge'
    assert result['source']==str(p)
    assert client.post('/editor-assistant/tool',json={**body,'args':{'name':'missing'}}).json()['ok'] is False
    assert client.post('/editor-assistant/tool',json={**body,'args':{'name':'../example'}}).json()['ok'] is False
    reference=p.parent/'references'/'design.md';reference.parent.mkdir();reference.write_text('specific composition guidance',encoding='utf8')
    result=client.post('/editor-assistant/tool',json={**body,'args':{'name':'example/references/design.md'}}).json()
    assert result['text']=='specific composition guidance'
    assert result['source']==str(reference)
    for name in ('example/../example/SKILL.md','example/references/missing.md','example/references/design.py'):
        assert client.post('/editor-assistant/tool',json={**body,'args':{'name':name}}).json()['ok'] is False


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
