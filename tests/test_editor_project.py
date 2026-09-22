import json
import copy
from types import SimpleNamespace
import pytest
from app.services import editor_project as project, timeline_draft as td, timeline_live as tl
from app.api import production_asset_routes as production
from scripts.repair_editor_aspect import restore, damaged_geometry

@pytest.fixture
def room(tmp_path,monkeypatch):
    monkeypatch.setattr(td,'UPLOAD_ROOT',tmp_path)
    p=tmp_path/'room';p.mkdir()
    seq={'format':'16:9','duration':3,'tracks':[{'id':'v','type':'video','clips':[{'id':'a','text':'字幕','timeline_start':0,'timeline_end':3,'style':{'fontSize':.85}}]}]}
    (p/'contents.json').write_text(json.dumps([{'id':'c','timeline':{'format':'16:9','sequence':seq},'creative_brief':{'taste':'実写'}}]))
    (p/'assets.json').write_text('[]')
    return p,seq

def test_partial_prepared_timeline_keeps_format_and_other_metadata():
    seq={'format':'16:9','tracks':[]}
    result=production._prepared_timeline({'format':'16:9','subseqs':{'other':{}},'brief':'keep'}, {}, {'sequence':seq},seq)
    assert result['format']=='16:9' and result['brief']=='keep' and 'other' in result['subseqs']

def test_old_busy_error_is_not_current_work(room):
    p,_=room
    (p/'jobs.json').write_text(json.dumps([{'id':'old','content_id':'c','status':'failed','error':'別ジョブが実行中','instruction':{}}]))
    result=project.current_status('room','c')
    assert result['active_count']==0 and result['active_jobs']==[]
    assert 'jobs' not in result and 'work' not in result
    assert result['latest_finished_job']['status']=='failed'


def test_inspection_reads_animation_detail_only_when_requested(room):
    from app.services import editor_workflows
    p,seq=room
    keys=[{'t':i/30,'x':i*.001} for i in range(90)]
    seq['tracks'][0]['clips'][0]['transform_keys']=keys
    rows=json.loads((p/'contents.json').read_text());rows[0]['timeline']['sequence']=seq
    (p/'contents.json').write_text(json.dumps(rows))
    compact=project.inspect_range('room','c',0,3)['clips'][0]
    assert 'transform_keys' not in compact
    assert compact['transform_key_summary']['count']==90
    exact=project.inspect_range('room','c',0,3,True)['clips'][0]
    assert exact['transform_keys']==keys
    assert editor_workflows.compact_state('room','c')['clips'][0]['transform_key_summary']['last']==keys[-1]
    assert editor_workflows.compact_state('room','c',include_keyframes=True)['clips'][0]['transform_keys']==keys
    assert json.loads((p/'contents.json').read_text())[0]['timeline']['sequence']==seq

def test_commit_repairs_missing_outer_format(room):
    p,seq=room
    docs=json.loads((p/'contents.json').read_text());docs[0]['timeline'].pop('format')
    (p/'contents.json').write_text(json.dumps(docs))
    r=tl.apply_edit('room','c','set_clip',{'clip_id':'a','text':'変更'})
    assert r['committed']
    saved=json.loads((p/'contents.json').read_text(encoding='utf-8'))[0]
    assert saved['timeline']['format']==saved['format']==saved['timeline']['sequence']['format']=='16:9'

def test_finished_execution_preserves_unfinished_request_outcome(room):
    p,_=room
    outcome={'state':'needs_user','summary':'Login required'}
    (p/'jobs.json').write_text(json.dumps([{'id':'j','content_id':'c','status':'done','instruction':{},
        'result':{'committed':False,'outcome':outcome,'summary':'Login required'}}]))
    result=project.current_status('room','c')
    assert result['active_count']==0
    assert result['latest_finished_job']['outcome']==outcome
    assert result['latest_finished_job']['summary']=='Login required'

def test_work_and_job_details_survive_reconnection_without_timeline_change(room):
    p,seq=room
    project.update_work('room','c','image','画像を追加','running',job_id='job')
    (p/'jobs.json').write_text(json.dumps([{'id':'job','content_id':'c','status':'running','instruction':{'revision_text':'画像追加'}}]))
    event=p/'jobs/job/events.jsonl';event.parent.mkdir(parents=True)
    event.write_text(json.dumps({'type':'status','model':'fable','text':'editing'})+'\n'+json.dumps({'type':'generation','model':'gpt_image_2','text':'画像生成中'}))
    result=project.status('room','c')
    assert result['work'][0]['title']=='画像を追加'
    assert result['jobs'][0]['editing_model']=='fable'
    assert result['jobs'][0]['events'][-1]['text']=='画像生成中'
    assert tl.live_sequence('room','c')[1]==seq
    with event.open('a') as stream:
        stream.write('\n{"type":')
    partial=project.status('room','c')
    assert partial['jobs'][0]['events']==result['jobs'][0]['events']

def test_progress_messages_survive_worker_keepalives(room):
    p,_=room
    (p/'jobs.json').write_text(json.dumps([{'id':'job','content_id':'c','status':'running','instruction':{}}]))
    event=p/'jobs/job/events.jsonl';event.parent.mkdir(parents=True)
    rows=[{'type':'text','text':'Login completed'}]+[{'type':'keepalive'} for _ in range(12)]
    event.write_text('\n'.join(json.dumps(row) for row in rows))
    assert project.current_status('room','c')['active_jobs'][0]['events'][0]['text']=='Login completed'

def test_recovery_preserves_new_material_and_refuses_unrelated_changes(room):
    _,seq=room
    original=copy.deepcopy(seq)
    original['tracks'][0]['clips'].append({'id':'image','asset_id':'new-image','timeline_start':0,'timeline_end':3,'position':{'x':0,'y':0,'width':1,'height':1}})
    bad=copy.deepcopy(original)
    bad['tracks'][0]['clips']=[damaged_geometry(c) for c in bad['tracks'][0]['clips']]
    fixed,count=restore(bad,original)
    assert fixed==original and count==2
    bad['tracks'][0]['clips'][0]['style']['fontSize']=2.99
    with pytest.raises(ValueError):restore(bad,original)
