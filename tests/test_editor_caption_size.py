import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from app.services import timeline_commands as tc, timeline_live as tl, timeline_draft as td, editor_workflows as w, timeline_scope as scope
from app.api import editor_assistant_routes as api


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(td, 'UPLOAD_ROOT', tmp_path)
    monkeypatch.setattr(api, '_get_user', lambda _: SimpleNamespace(user_id='owner'))
    folder=tmp_path/'room';folder.mkdir()
    seq={'duration':150,'format':'16:9','tracks':[{'id':'v','type':'video','clips':[
        {'id':'a','text':'車台番号の欄と、初度登録年月の欄です','timeline_start':101,'timeline_end':105,'style':{'fontSize':.85,'color':'#ffffff'}},
        {'id':'b','text':'弊社最近公式LINEも始めました','timeline_start':133,'timeline_end':136,'style':{'fontSize':.85}}]}]}
    (folder/'contents.json').write_text(json.dumps([{'id':'test','timeline':{'sequence':seq}}]))
    (folder/'assets.json').write_text('[]')
    return seq


@pytest.mark.parametrize('style',[{'font_size':'larger'},{'font_size':52},{'fontSize':'larger'},{'fontSize':float('nan')},{'fontSize':0}])
def test_invalid_style_is_atomic(project,style):
    before=copy.deepcopy(project)
    assert not tc.set_clip(project,clip_id='a',text='must not change',style=style)['ok']
    assert before==project


def test_noop_does_not_commit(project):
    result=tl.apply_edit('room','test','set_clip',{'clip_id':'a','style':{'fontSize':.85}})
    assert result['committed'] is False and result['changed'] is False
    assert td._content_sequence(td._read_contents_raw('room')[0])==project


def test_resize_keeps_other_caption_and_conversation_after_seek(project):
    b=api.begin(None,api.Context(room_id='room',content_id='test',input_mode='voice',playhead=104,selected=[{'id':'a'}],utterance='この字幕を少し大きくして'))
    def tool(turn,name,args):
        return asyncio.run(api.tool(None,api.ToolRequest(room_id='room',turn_id=turn,name=name,args=args)))
    result=tool(b['turn_id'],'resize_captions',{'clip_ids':['a'],'factor':1.25})
    assert result['committed'] and result['changes'][0]['after']['style']['fontSize']==1.0625
    c=api.begin(None,api.Context(room_id='room',content_id='test',input_mode='voice',playhead=134,selected=[{'id':'b'}],previous_turn=b['turn_id'],utterance='もっと大きくして'))
    history=c['context']['recent_conversation']
    assert history[0]['results'][0]['result']['changes'][0]['text']==project['tracks'][0]['clips'][0]['text']
    assert tool(c['turn_id'],'resize_captions',{'clip_ids':['a'],'factor':1.25})['committed']
    after=td._content_sequence(td._read_contents_raw('room')[0])
    assert scope.clips(after)['a'][1]['style']['fontSize']==1.328125
    assert scope.clips(after)['b']==scope.clips(project)['b']
    _, saved = api.read_turn('room',c['turn_id'],'owner')
    assert 101 <= saved['verify_at'] < 105


def test_resize_respects_selection_and_approval(project):
    with pytest.raises(ValueError):
        w.resize_captions('room','test',['a'],float('nan'),None,td.sequence_hash(project))
    result=w.resize_captions('room','test',['a'],1.25,scope.make_scope(project,['b']),td.sequence_hash(project))
    assert not result['ok']
    assert td._content_sequence(td._read_contents_raw('room')[0])==project
