"""Real GPT Image new/edit smoke through the production timeline MCP tool."""
import asyncio,json,uuid
from pathlib import Path
from app.services import timeline_draft as td
from app.services.editor_media import import_media
import app.timeline_mcp_server as m

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'exports/look-frame-flow';OUT.mkdir(parents=True,exist_ok=True)
ROOM='look-frame-flow-20260924'
folder=td._room_dir(ROOM);folder.mkdir(parents=True,exist_ok=True)
if not (folder/'contents.json').exists():
    td._write_contents_raw(ROOM,[{'id':'look-frame-proof','title':'完成イメージの会話修正検証','format':'16:9','timeline':{'sequence':{'format':'16:9','tracks':[]}}}])
m.ROOM_ID=ROOM;m.DRAFT_ID=td.create_draft(ROOM,'look-frame-proof')['draft_id'];m.JOB_ID='look-frame-proof'

async def main():
    if (OUT/'first.json').exists():first=json.loads((OUT/'first.json').read_text(encoding='utf8'))
    else:
        source=import_media(ROOM,str(ROOT/'exports/conte-finish-proof/appearance.png'),'作業場の見た目')
        assert source['ok'],source
        first=json.loads((await m.call_tool('generate_look_frame',{'prompt':'Use the reference as the same film scene. Preserve the Japanese engineer, his face, navy jacket, khaki trousers, the aluminum winged prototype car, camera composition, workshop and all object positions. Show a photorealistic finished film still in late-afternoon warm sunlight. Change only lighting/time of day. No text.','title':'作業場・夕方の光','reference_asset_ids':[source['asset_id']]}))[0].text)
        (OUT/'first.json').write_text(json.dumps(first,ensure_ascii=False,indent=2),encoding='utf8')
    assert first.get('ok'),first
    print('FIRST',first['model'],first['elapsed_seconds'],flush=True)
    item=first['presentation']['items'][0]
    second=json.loads((await m.call_tool('generate_look_frame',{'prompt':'Only change the lighting to an overcast soft daylight with cool shadows. Preserve the SAME person, face, clothing, vehicle geometry, props, workshop layout and camera composition. No other changes. Photorealistic film still. No text.','title':'作業場・曇りの光','revises':item['id']}))[0].text)
    (OUT/'second.json').write_text(json.dumps(second,ensure_ascii=False,indent=2),encoding='utf8')
    assert second.get('ok'),second
    import shutil
    shutil.copyfile(first['path'],OUT/'first.png');shutil.copyfile(second['path'],OUT/'second.png')
    print('SECOND',second['model'],second['elapsed_seconds'],flush=True)

asyncio.run(main())
