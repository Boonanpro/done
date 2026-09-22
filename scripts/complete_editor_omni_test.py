"""Finish all four reference-driven backgrounds through editor generation/edit tools."""
import json,asyncio,math
from app.services import timeline_draft as td,timeline_live as tl,timeline_commands as tc
import app.timeline_mcp_server as m
from app.api.production_asset_routes import _render_sequence_job
r='editor-omni-input-038e08e1';p=td._room_dir(r)
c=td._read_contents_raw(r)[0];cid=c['id']
d=next(json.loads(x.read_text(encoding='utf-8')) for x in (p/'drafts').glob('*.json') if json.loads(x.read_text(encoding='utf-8')).get('content_id')==cid)
m.ROOM_ID=r;m.DRAFT_ID=d['draft_id'];m.JOB_ID='four-backgrounds'
manifest=p/'four-backgrounds.json'
results=json.loads(manifest.read_text()) if manifest.exists() else [json.loads((p/'model-result.json').read_text(encoding='utf-8'))]
original=td._content_sequence(c)['tracks'][0]['clips']
actions=['','Very slow camera movement while hot water pours into the coffee dripper; gentle steam in the morning backlight. Keep the hands anatomically stable.','Gentle steam rising from the coffee cup, tiny natural hand movement. Slow cinematic camera drift.','A peaceful cinematic hold on the morning cafe scene, subtle sunlight and steam movement, very slow camera push in.']
for i in range(len(results),4):
    a=tl._assets(r)[original[i]['asset_id']]
    args={'prompt':'Preserve the exact scene, composition, objects, colors and soft cinematic morning lighting of the reference image. '+actions[i]+' No new text, signs, people or objects. No cuts.',
          'aspect_ratio':'16:9','duration':4,'model':'gemini_omni_flash_1_1','reference_path':a['local_path'],'resolution':'720p'}
    print('GENERATING',i+1,flush=True)
    result=json.loads(asyncio.run(m.call_tool('generate_video',args))[0].text)
    assert result['ok'],result
    results.append(result);manifest.write_text(json.dumps(results),encoding='utf-8')
    print('GENERATED',i+1,result['metadata']['duration'],flush=True)
for c,result in zip(original,results):
    res=json.loads(asyncio.run(m.call_tool('set_clip_props',{'clip_id':c['id'],'props':{'asset_id':result['asset_id'],'source_start':0,'volume':0,'transform_keys':[]}}))[0].text)
    assert res['ok'],res
checked=json.loads(asyncio.run(m.call_tool('validate_draft',{}))[0].text)
print('VALIDATION',checked,flush=True)
result=td.commit_draft(r,m.DRAFT_ID,lambda s,r:tc.validate_sequence(s,tl._assets(r),asset_dir=str(p)))
assert result['ok'],result
live,_=tl.live_sequence(r,cid)
(p/'review').mkdir(exist_ok=True)
output=_render_sequence_job(r,'four-backgrounds',cid,{'timeline':live['timeline'],'no_register':True},p/'review')
(p/'four-backgrounds-export.json').write_text(json.dumps(output),encoding='utf-8')
print('EXPORTED',output['output_path'],flush=True)
