import asyncio
import json
from types import SimpleNamespace

import pytest

from app.api import editor_assistant_routes as api
from app.api.production_asset_routes import ProductionContent
from app.services import timeline_draft as td


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(td, 'UPLOAD_ROOT', tmp_path)
    monkeypatch.setattr(api, '_get_user', lambda _: SimpleNamespace(user_id='owner'))
    folder = tmp_path / 'room'
    folder.mkdir()
    (folder / 'contents.json').write_text('[]')
    (folder / 'assets.json').write_text('[]')
    created = api.new_content(None, api.NewContent(room_id='room'))
    return created['content_id']


def test_new_project_is_compatible_with_content_listing(project):
    content = td._read_contents_raw('room')[0]
    assert ProductionContent.model_validate(content).id == project


def test_empty_project_can_create_without_selecting_nonexistent_clip(project):
    result=api.begin(None,api.Context(room_id='room',content_id=project))
    assert result['can_edit']
    _,turn=api.read_turn('room',result['turn_id'],'owner')
    assert turn['scope'] is None

def test_answer_survives_finished_worker_and_unrelated_null_context(project):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.services import editor_questions
    folder=td._room_dir('room')
    (folder/'jobs.json').write_text(json.dumps([{'id':'finished','content_id':project,'status':'done'}]))
    path=editor_questions.path('room','finished');path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'id':'q','job_id':'finished','text':'Which direction?'}))
    app=FastAPI();app.include_router(api.router)
    response=TestClient(app).post('/editor-assistant/answer',json={
        'room_id':'room','content_id':project,'job_id':'finished','question_id':'q',
        'text':'The third one','pointer':None,'selected':None,'playhead':None})
    assert response.status_code==200, response.text
    assert response.json()['delivery']=='saved'
    assert json.loads((path.parent/'q.answer.json').read_text())['text']=='The third one'
    assert editor_questions.read('room','finished') is None


def test_brief_is_saved_without_changing_timeline(project):
    before = td._content_sequence(td._read_contents_raw('room')[0])
    begun = api.begin(None, api.Context(room_id='room', content_id=project, scope_mode='whole'))
    result = asyncio.run(api.tool(None, api.ToolRequest(room_id='room', turn_id=begun['turn_id'],
        name='save_brief', args={'intent': '商品紹介', 'taste': '落ち着いた実写'})))
    content = td._read_contents_raw('room')[0]
    assert result['ok'] and content['creative_brief']['taste'] == '落ち着いた実写'
    assert td._content_sequence(content) == before


def test_existing_project_without_selection_is_read_only_but_whole_project_can_edit(project):
    initial=api.begin(None,api.Context(room_id='room',content_id=project))
    made=asyncio.run(api.tool(None,api.ToolRequest(room_id='room',turn_id=initial['turn_id'],
        name='timeline_edit',args={'op':'add_caption','args':{'text':'既存','timeline_start':0,'timeline_end':1}})))
    assert made['committed']
    selected = api.begin(None, api.Context(room_id='room', content_id=project))
    assert not selected['can_edit']
    rejected = asyncio.run(api.tool(None, api.ToolRequest(room_id='room', turn_id=selected['turn_id'],
        name='timeline_edit', args={'op': 'add_caption', 'args': {'text': '字幕', 'timeline_start': 0, 'timeline_end': 3}})))
    assert not rejected['ok']
    whole = api.begin(None, api.Context(room_id='room', content_id=project, scope_mode='whole'))
    accepted = asyncio.run(api.tool(None, api.ToolRequest(room_id='room', turn_id=whole['turn_id'],
        name='timeline_edit', args={'op': 'add_caption', 'args': {'text': '字幕', 'timeline_start': 0, 'timeline_end': 3}})))
    assert accepted['committed']


def test_user_approval_blocks_agent_until_user_unlocks(project):
    contents = td._read_contents_raw('room')
    contents[0]['timeline']['sequence'].update(duration=3, tracks=[{'id': 'v', 'type': 'video', 'clips': [
        {'id': 'a', 'text': '承認する字幕', 'timeline_start': 0, 'timeline_end': 3}]}])
    td._write_contents_raw('room', contents)
    approval = api.Approval(room_id='room', content_id=project, selected=[{'id': 'a'}], approved=True)
    assert api.approval(None, approval)['count'] == 1
    begun = api.begin(None, api.Context(room_id='room', content_id=project, selected=[{'id': 'a'}]))
    changed = asyncio.run(api.tool(None, api.ToolRequest(room_id='room', turn_id=begun['turn_id'],
        name='timeline_edit', args={'op': 'set_clip', 'args': {'clip_id': 'a', 'text': '事故'}})))
    assert not changed['ok']
    approval.approved = False
    api.approval(None, approval)
    assert 'approved' not in td._read_contents_raw('room')[0]['timeline']['sequence']['tracks'][0]['clips'][0]


def populated(project):
    contents = td._read_contents_raw('room')
    contents[0]['timeline']['sequence'].update(duration=6, tracks=[{'id': 'v', 'type': 'video', 'clips': [
        {'id': 'a', 'text': '対象', 'timeline_start': 0, 'timeline_end': 3},
        {'id': 'b', 'text': '維持', 'timeline_start': 3, 'timeline_end': 6}]}])
    td._write_contents_raw('room', contents)
    return contents[0]['timeline']['sequence']


def call(turn, name, args=None):
    return asyncio.run(api.tool(None, api.ToolRequest(room_id='room', turn_id=turn['turn_id'], name=name, args=args or {})))


def test_voice_resolves_target_without_mandatory_confirmation(project):
    before = populated(project)
    turn = api.begin(None, api.Context(room_id='room', content_id=project, input_mode='voice'))
    assert call(turn, 'resolve_target', {'clip_ids': ['a']})['ok']
    result = call(turn, 'timeline_edit', {'op': 'set_clip', 'args': {'clip_id': 'a', 'text': '変更'}})
    assert result['committed']
    seq = td._content_sequence(td._read_contents_raw('room')[0])
    assert seq['tracks'][0]['clips'][1] == before['tracks'][0]['clips'][1]
    assert not call(turn, 'timeline_edit', {'op': 'set_clip', 'args': {'clip_id': 'b', 'text': '事故'}})['ok']


def test_text_cannot_infer_scope_from_pointer(project):
    populated(project)
    turn = api.begin(None, api.Context(room_id='room', content_id=project, pointer={'x': .4, 'y': .5}))
    assert not call(turn, 'resolve_target', {'clip_ids': ['a']})['ok']


def test_proposal_does_not_edit_and_can_be_confirmed_in_following_turn(project):
    before = populated(project)
    turn = api.begin(None, api.Context(room_id='room', content_id=project, input_mode='voice'))
    proposal = call(turn, 'propose_target', {'clip_ids': ['a'], 'rect': [.1,.1,.5,.5], 'start': 0, 'end': 3, 'label': 'この字幕？'})
    assert proposal['editor_action']['kind'] == 'focus'
    assert td._content_sequence(td._read_contents_raw('room')[0]) == before
    assert not call(turn, 'confirm_target')['ok']
    next_turn = api.begin(None, api.Context(room_id='room', content_id=project, input_mode='voice', target_turn=turn['turn_id']))
    assert call(next_turn, 'confirm_target')['edit_scope']['clip_ids'] == ['a']


def test_interrupted_turn_cannot_apply_late_tool_calls(project):
    before = populated(project)
    turn = api.begin(None, api.Context(room_id='room', content_id=project, selected=[{'id':'a'}]))
    asyncio.run(api.cancel(None, api.ToolRequest(room_id='room', turn_id=turn['turn_id'], name='cancel')))
    assert not call(turn, 'timeline_edit', {'op': 'set_clip', 'args': {'clip_id':'a','text':'遅れて反映'}})['ok']
    assert td._content_sequence(td._read_contents_raw('room')[0]) == before


def test_music_lookup_accepts_music_kind_and_does_not_hide_unlabelled_tracks(project):
    path=td._room_dir('room')/'track.mp3';path.write_bytes(b'fixture')
    (td._room_dir('room')/'assets.json').write_text(json.dumps([{
        'id':'music','kind':'audio','filename':'A song.mp3','local_path':str(path),'metadata':{'duration':20}}]))
    turn=api.begin(None,api.Context(room_id='room',content_id=project))
    found=call(turn,'list_assets',{'kind':'music','query':'企業向けの落ち着いた音楽'})
    assert found['assets'][0]['id']=='music'


def test_explicit_global_voice_request_can_add_music_without_clip_selection(project):
    turn=api.begin(None,api.Context(room_id='room',content_id=project,input_mode='voice'))
    assert call(turn,'set_project_scope',{'instruction':'動画全体にBGMを付けて'})['ok']
    _,saved=api.read_turn('room',turn['turn_id'],'owner')
    assert saved['scope'] is None

def test_voice_addition_binds_its_time_without_unlocking_existing_clips(project):
    before=populated(project)
    turn=api.begin(None,api.Context(room_id='room',content_id=project,input_mode='voice'))
    result=call(turn,'batch_edit',{'operations':[{'op':'add_caption','args':{'text':'new','timeline_start':4,'timeline_end':5,'lane':'front'}}]})
    assert result['committed']
    after=td._content_sequence(td._read_contents_raw('room')[0])
    assert after['tracks'][0]==before['tracks'][0]
    # A subsequent call in the same voice turn must not borrow this new span to
    # change an old clip that was never identified as the edit target.
    rejected=call(turn,'batch_edit',{'operations':[{'op':'set_clip','args':{'clip_id':'b','text':'wrong'}}]})
    assert not rejected['ok']
    assert td._content_sequence(td._read_contents_raw('room')[0])==after


def test_voice_addition_still_protects_approved_time(project):
    populated(project)
    api.approval(None,api.Approval(room_id='room',content_id=project,selected=[{'id':'b'}],approved=True))
    before=td._content_sequence(td._read_contents_raw('room')[0])
    turn=api.begin(None,api.Context(room_id='room',content_id=project,input_mode='voice'))
    rejected=call(turn,'batch_edit',{'operations':[{'op':'add_caption','args':{'text':'cover','timeline_start':4,'timeline_end':5,'lane':'front'}}]})
    assert not rejected['ok']
    assert td._content_sequence(td._read_contents_raw('room')[0])==before
