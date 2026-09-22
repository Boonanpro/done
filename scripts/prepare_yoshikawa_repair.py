"""Measured repair in an isolated editable project. No live project write."""
import copy
import json
import os
import shutil
import uuid
from app.services import timeline_live as tl,timeline_draft as td,timeline_scope as scope,timeline_context as tcx

source='a3970e0b-f7dc-472e-ad63-e8c51382ddb3'
cid='277f96d8-2609-43e9-ba18-bcf3ea37f576'
room='yoshikawa-repair-'+uuid.uuid4().hex[:8]
folder=td._room_dir(room);folder.mkdir(parents=True)
content,seq=tl.live_sequence(source,cid);before=copy.deepcopy(seq)
content['room_id']=room
shutil.copy2(td._room_dir(source)/'assets.json',folder/'assets.json')
for f in td._room_dir(source).glob('*_proxy.mp4'):os.link(f,folder/f.name)
clips=scope.clips(seq)
# Existing spoken line is source 141.2..159.6, not raw-camera 141.9.
v=clips['clip_ag_v_83f7155fd3'][1]
v.update(source_start=162.896625,source_end=181.296625,timeline_end=168.1)
audio=clips['clip_ag_a_c8000a742d'][1]
audio.update(source_start=v['source_start'],source_end=v['source_end'],timeline_end=168.1)
base=next(t for t in seq['tracks'] if t['id']==clips[v['id']][0])
def freeze(template,start,end,source_time,name):
    c=copy.deepcopy(template)
    c.update(id=name,freeze=True,source_start=source_time,source_end=source_time,timeline_start=start,timeline_end=end)
    c.pop('link_id',None);base['clips'].append(c)
freeze(v,168.1,168.7,181.27,'repair_pause_ending')
v2=clips['clip_ag_v_9c40267698'][1]
v2.update(source_start=183.87,source_end=190.37,timeline_end=175.2)
tail=copy.deepcopy(v2)
tail.update(id='repair_ending_last',source_start=191.19,source_end=195.39,timeline_start=175.2,timeline_end=179.4)
tail['link_id']='repair_ending_tail_link';base['clips'].append(tail)
freeze(tail,179.4,180,195.35,'repair_last_hold')
audio=clips['clip_ag_a_40609a03b2'][1]
audio.update(source_start=v2['source_start'],source_end=v2['source_end'],timeline_end=175.2)
audio_tail=copy.deepcopy(audio)
audio_tail.update(id='repair_ending_audio_tail',link_id=tail['link_id'],source_start=tail['source_start'],source_end=tail['source_end'],timeline_start=175.2,timeline_end=179.4)
next(t for t in seq['tracks'] if t['id']==clips[audio['id']][0])['clips'].append(audio_tail)
# Reference-based visual and actual topic boundary. Narration/captions unchanged.
assets=json.loads((folder/'assets.json').read_text(encoding='utf-8'))
recovered=next(a for a in tl._assets('assistant-reference-test-027b0895').values() if a['id']=='recovered_reference_parts')
assets.append(recovered)
(folder/'assets.json').write_text(json.dumps(assets,ensure_ascii=False),encoding='utf-8')
first=clips['clip_ag_v_185fc71934'][1]
first.update(asset_id='recovered_reference_parts')
parts=clips['clip_ag_s_6e55992a3d'][1]
parts.update(asset_id='recovered_reference_parts',timeline_end=33.71,source_end=33.71-parts['timeline_start'])
year=clips['clip_ag_s_d872e34b34'][1]
year.update(timeline_start=33.71,source_start=0,source_end=year['timeline_end']-33.71)
base['clips'].sort(key=lambda c:c['timeline_start'])
content['timeline']['sequence']=seq
(folder/'contents.json').write_text(json.dumps([content],ensure_ascii=False),encoding='utf-8')
(folder/'repair-base.json').write_text(json.dumps(before,ensure_ascii=False),encoding='utf-8')
print('REPAIR',room,flush=True)
print(tcx.render_timeline_frames(seq,str(folder),[150,168,170,175.3,178.5,179.8]),flush=True)
