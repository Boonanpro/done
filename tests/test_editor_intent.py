import json
from app.services import timeline_draft as td, editor_intent as intent


def test_direction_change_preserves_other_agreements_and_reaches_active_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(td,'UPLOAD_ROOT',tmp_path)
    folder=tmp_path/'room';folder.mkdir()
    (folder/'contents.json').write_text(json.dumps([{'id':'content','creative_brief':{'intent':'explain repairs','taste':'animated people'}}]))
    from app.services import timeline_agent, editor_job_updates
    monkeypatch.setattr(timeline_agent,'content_busy',lambda cid:'worker')
    result=intent.save_brief('room','content',{'taste':'two still images with narration'})
    brief=td._read_contents_raw('room')[0]['creative_brief']
    assert brief['intent']=='explain repairs'
    assert brief['taste']=='two still images with narration'
    assert result['delivery']['state']=='instruction_pending'
    pending=editor_job_updates.pending('room','worker')
    assert len(pending)==1 and 'two still images with narration' in pending[0]['instruction']
    assert not intent.save_brief('room','content',{'taste':brief['taste']})['changed']
    assert len(editor_job_updates.pending('room','worker'))==1
