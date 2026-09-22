import json
import asyncio
import pytest
from app.services import timeline_draft as td


@pytest.fixture
def draft(tmp_path, monkeypatch):
    monkeypatch.setattr(td, 'UPLOAD_ROOT', tmp_path)
    folder = tmp_path / 'room'
    folder.mkdir()
    seq = {'duration': 3, 'format': '16:9', 'tracks': []}
    (folder / 'contents.json').write_text(json.dumps([{'id': 'content', 'timeline': {'sequence': seq}}]))
    return td.create_draft('room', 'content', job_id='test')


def test_batch_persists_once_and_rolls_back_failed_edits(draft, monkeypatch):
    original = td.draft_path('room', draft['draft_id']).read_bytes()
    calls = []
    replace = td.os.replace
    monkeypatch.setattr(td.os, 'replace', lambda a, b: (calls.append(str(b)), replace(a, b))[1])
    with pytest.raises(ValueError):
        with td.edit_transaction('room', draft['draft_id']):
            current = td.load_draft('room', draft['draft_id'])
            current['sequence']['duration'] = 7
            td.save_draft(current)
            assert td.load_draft('room', draft['draft_id'])['sequence']['duration'] == 7
            raise ValueError('invalid later operation')
    assert td.draft_path('room', draft['draft_id']).read_bytes() == original
    assert calls == []
    with td.edit_transaction('room', draft['draft_id']):
        for n in range(100):
            current = td.load_draft('room', draft['draft_id'])
            current['sequence']['duration'] = n
            td.save_draft(current)
    assert len(calls) == 1
    assert td.load_draft('room', draft['draft_id'])['sequence']['duration'] == 99


def test_real_mcp_batch_rolls_back_and_publishes_complete_scene(draft,monkeypatch):
    from app import timeline_mcp_server as m
    monkeypatch.setattr(m,'ROOM_ID','room')
    monkeypatch.setattr(m,'DRAFT_ID',draft['draft_id'])
    monkeypatch.setattr(m,'JOB_ID','test')
    draft['live_updates']=True
    td.save_draft(draft)
    add={'name':'add_caption','args':{'text':'scene','timeline_start':0,'timeline_end':3}}
    bad={'name':'remove_clip','args':{'clip_id':'missing'}}
    result=json.loads(m._run_tool_thread('apply_edits',{'operations':[add,bad]})[0].text)
    assert result['rolled_back']
    assert not td._content_sequence(td._read_contents_raw('room')[0])['tracks']
    result=json.loads(m._run_tool_thread('apply_edits',{'operations':[add]})[0].text)
    assert result['timeline_updated']
    clips=[c for t in td._content_sequence(td._read_contents_raw('room')[0])['tracks'] for c in t['clips']]
    assert len(clips)==1 and clips[0]['text']=='scene'


def test_terminal_job_clears_persisted_work_state(draft,monkeypatch):
    from app.api import production_asset_routes as api
    jobs=[{'id':'j','status':'running'}]
    contents=[{'id':'c','editor_work':[{'job_id':'j','status':'running'},{'job_id':'other','status':'running'}]}]
    monkeypatch.setattr(api,'_read_jobs',lambda _:jobs)
    monkeypatch.setattr(api,'_write_jobs',lambda *args:None)
    monkeypatch.setattr(api,'_read_contents',lambda _:contents)
    saved=[]
    monkeypatch.setattr(api,'_write_contents',lambda room,rows:saved.append(rows))
    api._update_job('room','j',{'status':'done'})
    assert saved[0][0]['editor_work'][0]['status']=='done'
    assert saved[0][0]['editor_work'][1]['status']=='running'


def test_production_receives_update_without_a_timeline_tool(draft,monkeypatch,tmp_path):
    import queue
    from app.services import editor_production_session as session, editor_job_updates as updates
    folder=td._room_dir('room')/'jobs'/'test'
    folder.mkdir(parents=True)
    config=folder/'mcp.json';config.write_text('{"mcpServers":{}}')
    owners=[]
    class Owner:
        def __init__(self):
            self.serial=0;self.events=queue.Queue();self.closed=False;owners.append(self)
        async def rpc(self,method,args):
            if method=='account/read':return {'account':{'type':'chatgpt'}}
            if method=='thread/start':return {'thread':{'id':'thread'}}
            if method=='turn/start':
                updates.submit('room','test','最新の依頼')
                return {'turn':{'id':'turn'}}
            return {}
        def send(self,event):
            if event.get('method')=='turn/steer':
                assert event['params']['input'][0]['text']=='最新の依頼'
                self.events.put({'id':event['id'],'result':{}})
                self.events.put({'method':'turn/completed','params':{'turn':{'status':'completed'}}})
    monkeypatch.setattr(session,'CodexTurn',Owner)
    monkeypatch.setattr(session,'close_owner',lambda owner:setattr(owner,'closed',True))
    events=[]
    result=asyncio.run(session.run('room','content','test','request','instructions',config,'gpt-6-astra',events.append))
    assert not result['is_error'] and not updates.pending('room','test')
    assert any(e['type']=='instruction_received' for e in events)
    assert owners[0].closed
