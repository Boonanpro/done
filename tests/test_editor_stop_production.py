import asyncio
import json
from tests.test_editor_assistant_routes import project
from app.api import editor_assistant_routes as api, production_asset_routes as production
from app.services import timeline_draft as td, editor_project


def test_stop_is_scoped_to_current_content(project,monkeypatch):
    rows=[{'id':'ours','content_id':project,'status':'running'},
          {'id':'other','content_id':'different','status':'running'},
          {'id':'done','content_id':project,'status':'done'}]
    (td._room_dir('room')/'jobs.json').write_text(json.dumps(rows))
    called=[]
    monkeypatch.setattr(production,'cancel_production_job',lambda job,room:called.append(job) or {'ok':True})
    begun=api.begin(None,api.Context(room_id='room',content_id=project))
    result=asyncio.run(api.tool(None,api.ToolRequest(room_id='room',turn_id=begun['turn_id'],name='stop_production',args={})))
    assert result['ok'] and called==['ours']
    assert not editor_project.stop_production('room',project,'other')['ok']


def test_cancel_prevents_late_commit(project):
    draft=td.create_draft('room',project,'stopped')
    before=(td._room_dir('room')/'contents.json').read_bytes()
    folder=td._room_dir('room')/'jobs'/'stopped';folder.mkdir(parents=True)
    (folder/'cancel-requested').touch()
    result=td.commit_draft('room',draft['draft_id'],lambda *args:[])
    assert not result['ok']
    assert (td._room_dir('room')/'contents.json').read_bytes()==before


def test_interrupt_does_not_wait_for_long_running_tool(project):
    async def scenario():
        begun=api.begin(None,api.Context(room_id='room',content_id=project))
        body=api.ToolRequest(room_id='room',turn_id=begun['turn_id'],name='cancel')
        async with api._turn_lock('room',begun['turn_id']):
            result=await asyncio.wait_for(api.cancel(None,body),.5)
            assert result['ok'] and result['operation_finishing']
            assert api.read_turn('room',begun['turn_id'],'owner')[1]['canceled']
    asyncio.run(scenario())
