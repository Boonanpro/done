import json
import pytest
from app import timeline_mcp_server as server

@pytest.mark.asyncio
async def test_disallowed_generation_never_reaches_provider(monkeypatch):
    monkeypatch.setattr(server,'_load',lambda:{'sequence':{}})
    monkeypatch.setattr(server,'_assets',lambda:{})
    monkeypatch.setattr(server,'_generate_video',lambda *a,**k:pytest.fail('paid video invoked'))
    monkeypatch.setattr(server,'_generate_image',lambda *a,**k:pytest.fail('other image provider invoked'))
    for name,args in [('generate_video',{'prompt':'x','provider':'unknown'}),('generate_image',{'model':'other','prompt':'x'})]:
        result=await server._dispatch(name,args)
        assert json.loads(result[0].text)['ok'] is False

@pytest.mark.asyncio
async def test_allowed_image_alias_uses_gpt_image_2(monkeypatch):
    monkeypatch.setattr(server,'_load',lambda:{'sequence':{}})
    monkeypatch.setattr(server,'_assets',lambda:{})
    monkeypatch.setattr(server,'_generations',0)
    calls=[]
    monkeypatch.setattr(server,'_generate_image',lambda *args:(calls.append(args) or {'ok':True}))
    await server._dispatch('generate_image',{'model':'gpt-image-2','prompt':'x'})
    assert calls[0][-1]=='gpt_image_2'


@pytest.mark.asyncio
async def test_google_direct_is_default_and_registers_result(monkeypatch, tmp_path):
    from app.services import google_video
    monkeypatch.setattr(server,'_load',lambda:{'sequence':{'format':'16:9'}})
    monkeypatch.setattr(server,'_assets',lambda:{})
    monkeypatch.setattr(server,'_room_dir',lambda:tmp_path)
    monkeypatch.setattr(server,'_generations',0)
    monkeypatch.setattr(server,'_generate_video',lambda *a:pytest.fail('Higgsfield was invoked'))
    calls=[]
    registered=[]
    (tmp_path/'out.mp4').write_bytes(b'cached provider result')
    monkeypatch.setattr(google_video,'generate',lambda *a:(calls.append(a) or {'path':str(tmp_path/'out.mp4'),'metadata':{'generator':'google'},'reused':False}))
    monkeypatch.setattr(server,'_register_media_asset',lambda *a,**kw:registered.append((a,kw)))
    result=json.loads((await server._dispatch('generate_video',{'prompt':'new subject','reference_mode':'style'}))[0].text)
    assert result['ok'] and result['asset_id']
    assert calls[0][2]=='16:9' and calls[0][5]=='style'
    assert registered[0][1]['metadata']['generator']=='google'
    assert result['path']!=str(tmp_path/'out.mp4')
    assert (tmp_path/'out.mp4').read_bytes()==b'cached provider result'
