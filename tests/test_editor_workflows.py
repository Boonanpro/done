import copy
import json
import pytest
from app.services import editor_workflows as w,timeline_draft as td,timeline_scope as scope


@pytest.fixture
def project(tmp_path,monkeypatch):
    monkeypatch.setattr(td,'UPLOAD_ROOT',tmp_path)
    folder=tmp_path/'room';folder.mkdir()
    seq={'duration':6,'format':'16:9','tracks':[{'id':'v','type':'video','clips':[
        {'id':'a','text':'前半後半ですし','timeline_start':0,'timeline_end':4},
        {'id':'b','text':'残す字幕','timeline_start':4,'timeline_end':6}]}]}
    (folder/'contents.json').write_text(json.dumps([{'id':'test','timeline':{'sequence':seq}}]))
    (folder/'assets.json').write_text('[]')
    return seq


def test_split_uses_measured_speech_and_preserves_neighbor(project,monkeypatch):
    words=[(0,.8,'前半'),(1.7,3.8,'後半ですし')]
    monkeypatch.setattr(w,'measured_words',lambda *_:(words,[{'source':'test'}]))
    result=w.edit_captions('room','test',['a'],['前半','後半ですし'],False,scope.make_scope(project,['a']),td.sequence_hash(project))
    assert result['committed']
    assert result['captions'][0]['timeline_end']==1.7
    assert result['captions'][1]['text']=='後半ですし'
    after=td._content_sequence(td._read_contents_raw('room')[0])
    assert scope.clips(after)['b']==scope.clips(project)['b']
    assert len(td.load_draft('room',result['draft_id'])['log'])==1


def test_omitted_syllable_is_rejected_before_audio_work(project,monkeypatch):
    monkeypatch.setattr(w,'measured_words',lambda *_:pytest.fail('must reject omission first'))
    with pytest.raises(ValueError,match='省略'):
        w.edit_captions('room','test',['a'],['前半','後半です'],False,None,td.sequence_hash(project))
    assert td._content_sequence(td._read_contents_raw('room')[0])==project


def test_batch_failure_does_not_leave_first_operation_applied(project):
    with pytest.raises(ValueError):
        w.batch_edit('room','test',[{'op':'set_clip','args':{'clip_id':'a','text':'途中'}},
                                  {'op':'remove_clip','args':{'clip_id':'missing'}}],None,td.sequence_hash(project))
    assert td._content_sequence(td._read_contents_raw('room')[0])==project


def test_group_scale_is_one_commit_and_preserves_other_content(project):
    seq=copy.deepcopy(project)
    seq['tracks'].append({'id':'group','type':'video','clips':[{
        'id':'background','timeline_start':0,'timeline_end':4,'style':'solid',
        'region':{'x':.1,'y':.1,'width':.4,'height':.4}}]})
    seq['tracks'][0]['clips'][0]['style']={'x':.2,'y':.2,'fontSize':1,'maxWidth':.3}
    contents=td._read_contents_raw('room');contents[0]['timeline']['sequence']=seq;td._write_contents_raw('room',contents)
    result=w.transform_visuals('room','test',['a','background'],.8,{'x':.1,'y':.1},scope.make_scope(seq,['a','background']),td.sequence_hash(seq))
    assert result['committed']
    after=scope.clips(td._content_sequence(td._read_contents_raw('room')[0]))
    assert after['a'][1]['style']['x']==pytest.approx(.18)
    assert after['a'][1]['style']['fontSize']==.8
    assert after['background'][1]['region']=={'x':.1,'y':.1,'width':.32,'height':.32}
    assert after['b']==scope.clips(seq)['b']
    assert len(td.load_draft('room',result['draft_id'])['log'])==2


def test_mismatched_audio_is_not_spread_into_fake_timing():
    with pytest.raises(ValueError,match='一致'):
        w.caption_boundaries([(0,3,'別の台詞です')],['写真を','送ってください'],0,4)


def test_cancel_during_measurement_prevents_commit(project,monkeypatch):
    monkeypatch.setattr(w,'measured_words',lambda *_:([(0,.8,'前半'),(1.7,3.8,'後半ですし')],[]))
    with pytest.raises(ValueError,match='中止'):
        w.edit_captions('room','test',['a'],['前半','後半ですし'],False,None,td.sequence_hash(project),lambda:True)
    assert td._content_sequence(td._read_contents_raw('room')[0])==project


def test_compact_state_does_not_resend_whole_timeline(project):
    contents=td._read_contents_raw('room')
    contents[0]['timeline']['sequence']['tracks'][0]['clips'] += [
        {'id':str(i),'text':'long text'*100,'timeline_start':i*10,'timeline_end':i*10+5} for i in range(1,1000)]
    td._write_contents_raw('room',contents)
    result=w.compact_state('room','test',1)
    assert len(result['clips'])==2
    assert len(json.dumps(result))<1000

def test_direct_batch_can_create_then_edit_without_model_round_trip(project):
    result=w.batch_edit('room','test',[
        {'op':'add_caption','args':{'text':'new','timeline_start':1,'timeline_end':2,'lane':'front'}},
        {'op':'set_clip','args':{'clip_id':{'$result':0,'path':'clip_id'},'text':'final'}}
    ],None,td.sequence_hash(project))
    after=td._content_sequence(td._read_contents_raw('room')[0])
    assert result['committed'] and after['tracks'][-1]['clips'][0]['text']=='final'
    assert after['tracks'][0]==project['tracks'][0]


def test_direct_batch_rejects_edit_outside_selected_region(project):
    result=w.batch_edit('room','test',[{'op':'set_clip','args':{'clip_id':'b','text':'wrong target'}}],scope.make_scope(project,['a']),td.sequence_hash(project))
    assert not result['ok']
    assert td._content_sequence(td._read_contents_raw('room')[0])==project
