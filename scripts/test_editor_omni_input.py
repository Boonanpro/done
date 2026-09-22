"""Run the actual editor video tool with the explicitly requested model and source image."""
import copy,json,uuid,time,asyncio
from app.services import timeline_draft as td,timeline_live as tl
import app.timeline_mcp_server as m
r='editor-omni-input-'+uuid.uuid4().hex[:8];cid=uuid.uuid4().hex
c,_=tl.live_sequence('a3970e0b-f7dc-472e-ad63-e8c51382ddb3','a65ccfdd-6304-4dee-9fa4-c06d79ab921c')
c=copy.deepcopy(c);c['id']=cid;p=td._room_dir(r);p.mkdir(parents=True,exist_ok=True)
(p/'contents.json').write_text(json.dumps([c],ensure_ascii=False),encoding='utf-8')
assets=tl._assets('a3970e0b-f7dc-472e-ad63-e8c51382ddb3')
(p/'assets.json').write_text(json.dumps(list(assets.values()),ensure_ascii=False),encoding='utf-8')
d=td.create_draft(r,cid);m.ROOM_ID=r;m.DRAFT_ID=d['draft_id'];m.JOB_ID='model-input-check'
source=assets['ec2d577068bc']['local_path']
print('ROOM',r,'SOURCE_EXISTS',__import__('pathlib').Path(source).exists(),flush=True)
t=time.monotonic()
result=asyncio.run(m.call_tool('generate_video',{'prompt':'Keep the exact cafe exterior, composition, colors and morning lighting of the reference image. Create a quiet cinematic shot: a very slow gentle camera push in, subtle leaves moving in a light breeze. No people, no added signs, no text, no new buildings. Preserve the original visual style.', 'aspect_ratio':'16:9','duration':4,'model':'gemini_omni_flash_1_1','reference_path':source,'resolution':'720p'}))
data=json.loads(result[0].text);(p/'model-result.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
print('RESULT',json.dumps(data,ensure_ascii=False),'SECONDS',round(time.monotonic()-t,1),flush=True)
assert data['ok'],data
