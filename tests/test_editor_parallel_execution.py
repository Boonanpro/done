import asyncio,json,threading,time
import pytest
from tests.test_editor_assistant_routes import project
from app.services import timeline_draft as td
from app import timeline_mcp_server as m

@pytest.mark.asyncio
@pytest.mark.parametrize('operation',['generate_speech','render_motion_project'])
async def test_generation_wait_does_not_block_edit_and_registration_preserves_edit(project,monkeypatch,operation):
    d=td.create_draft('room',project,'j')
    monkeypatch.setattr(m,'ROOM_ID','room');monkeypatch.setattr(m,'JOB_ID','j');monkeypatch.setattr(m,'DRAFT_ID',d['draft_id'])
    started=threading.Event();release=threading.Event()
    original=m._dispatch
    async def dispatch(name,args):
        if name==operation:
            snapshot=m._load();started.set();assert release.wait(5)
            m._track_asset(snapshot,'generated')
            return m._ok({'ok':True})
        return await original(name,args)
    monkeypatch.setattr(m,'_dispatch',dispatch)
    task=asyncio.create_task(m.call_tool(operation,{'text':'x'}))
    try:
        assert await asyncio.to_thread(started.wait,2)
        edit=await asyncio.wait_for(m.call_tool('report_result',{'outcome':'achieved','summary':'Retain this edit'}),1)
        assert json.loads(edit[0].text)['ok']
    finally:release.set()
    await task
    current=td.load_draft('room',d['draft_id'])
    assert current['outcome']['summary']=='Retain this edit'
    assert current['generated_asset_ids']==['generated']


@pytest.mark.asyncio
async def test_edit_batch_rolls_back_earlier_operations_when_later_one_fails(project,monkeypatch):
    d=td.create_draft('room',project,'batch')
    monkeypatch.setattr(m,'ROOM_ID','room');monkeypatch.setattr(m,'JOB_ID','batch');monkeypatch.setattr(m,'DRAFT_ID',d['draft_id'])
    monkeypatch.setattr(m,'_ensure_caption_png',lambda *a:None)
    before=td.load_draft('room',d['draft_id'])
    result=await m.call_tool('apply_edits',{'operations':[
        {'name':'add_caption','args':{'text':'New text','timeline_start':30,'timeline_end':32}},
        {'name':'remove_clip','args':{'clip_id':'does-not-exist'}}]})
    value=json.loads(result[0].text)
    assert not value['ok'] and value['rolled_back']
    assert td.load_draft('room',d['draft_id'])==before


@pytest.mark.asyncio
async def test_edit_batch_updates_only_requested_clip_and_keeps_live_unchanged(project,monkeypatch):
    d=td.create_draft('room',project,'batch-success')
    monkeypatch.setattr(m,'ROOM_ID','room');monkeypatch.setattr(m,'JOB_ID','batch-success');monkeypatch.setattr(m,'DRAFT_ID',d['draft_id'])
    monkeypatch.setattr(m,'_ensure_caption_png',lambda *a:None)
    live=(td._room_dir('room')/'contents.json').read_bytes()
    before=td.load_draft('room',d['draft_id'])['sequence']
    result=await m.call_tool('apply_edits',{'operations':[
        {'name':'add_caption','args':{'text':'Temporary','timeline_start':30,'timeline_end':32}}]})
    assert json.loads(result[0].text)['ok']
    current=td.load_draft('room',d['draft_id'])['sequence']
    old={c['id']:c for t in before['tracks'] for c in t['clips']}
    new={c['id']:c for t in current['tracks'] for c in t['clips']}
    target=next(c for i,c in new.items() if i not in old)
    result=await m.call_tool('apply_edits',{'operations':[
        {'name':'set_clip','args':{'clip_id':target['id'],'text':'Revised'}},
        {'name':'set_clip','args':{'clip_id':target['id'],'style':{'color':'#225577'}}}]})
    assert json.loads(result[0].text)['ok']
    after={c['id']:c for t in td.load_draft('room',d['draft_id'])['sequence']['tracks'] for c in t['clips']}
    assert all(after[i]==c for i,c in old.items())
    assert after[target['id']]['text']=='Revised'
    assert after[target['id']]['style']['color']=='#225577'
    assert (td._room_dir('room')/'contents.json').read_bytes()==live
