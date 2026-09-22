"""Exercise the editor's real speech tool -> cloud -> local asset registration."""
import json
import time
import uuid
from app import timeline_mcp_server as m
from app.services import timeline_draft as td

room='cloud-voice-acceptance-'+uuid.uuid4().hex[:8]
folder=td._room_dir(room);folder.mkdir(parents=True,exist_ok=True)
content='voice-test'
(folder/'contents.json').write_text(json.dumps([{'id':content,'timeline':{'format':'16:9','sequence':{'duration':0,'format':'16:9','tracks':[]}}}]),encoding='utf-8')
(folder/'assets.json').write_text('[]',encoding='utf-8')
d=td.create_draft(room,content,'cloud-voice-test')
m.ROOM_ID=room;m.CONTENT_ID=content;m.DRAFT_ID=d['draft_id'];m.JOB_ID='cloud-voice-test'
t=time.monotonic()
result=m._generate_speech(d,'五つの情報を先に送ると、確認がスムーズに進みます。','owner',None,'cloud-route-test')
result['wall_seconds']=round(time.monotonic()-t,2)
print(json.dumps(result,ensure_ascii=False),flush=True)
assert result.get('ok') and result.get('backend')=='cloud',result
asset=next(a for a in json.loads((folder/'assets.json').read_text(encoding='utf-8')) if a['id']==result['asset_id'])
assert asset['metadata']['pod_id']=='4drusrkcie2ob6'
assert result['asset_id'] in td.load_draft(room,d['draft_id'])['generated_asset_ids']
(folder/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('PASS editor voice tool, cloud generation, local asset registration',room,flush=True)
