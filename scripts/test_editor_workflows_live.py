"""Real media, disposable timeline: measured caption regroup + BGM + region edit."""
import copy
import json
import shutil
import uuid
from pathlib import Path
from app.services import editor_workflows as w,timeline_live as tl,timeline_draft as td,timeline_scope as scope

source_room='a3970e0b-f7dc-472e-ad63-e8c51382ddb3'
cid='277f96d8-2609-43e9-ba18-bcf3ea37f576'
room='assistant-workflow-test-'+uuid.uuid4().hex[:8]
folder=td._room_dir(room);folder.mkdir(parents=True)
content,seq=tl.live_sequence(source_room,cid)
(folder/'contents.json').write_text(json.dumps([content],ensure_ascii=False),encoding='utf-8')
shutil.copy2(td._room_dir(source_room)/'assets.json',folder/'assets.json')
cache=td._room_dir(source_room)/'assistant/audio-analysis'
shutil.copytree(cache,folder/'assistant/audio-analysis')
before=copy.deepcopy(seq)
ids=['clip_ag_c_bf4202c7f5','clip_ag_c_f295fb9ee9']
r=w.edit_captions(room,cid,ids,['ちなみに少し話はそれますが、','弊社最近公式LINEも始めました'],False,
                  scope.make_scope(seq,ids),td.sequence_hash(seq))
assert r['committed'],r
assert abs(r['captions'][1]['timeline_start']-132.93)<.04,r
print('measured_caption',r['verification'],flush=True)
_,seq=tl.live_sequence(room,cid)
for id,value in scope.clips(before).items():
    if id not in ids:assert scope.clips(seq)[id]==value
before_music=copy.deepcopy(seq)
r=w.add_music(room,cid,'nat1785294316_72552',None,td.sequence_hash(seq))
assert r['committed'],r
print('music',r['verification'],flush=True)
_,seq=tl.live_sequence(room,cid)
for id,value in scope.clips(before_music).items():assert scope.clips(seq)[id]==value
assert seq['duration']==before_music['duration']
music=scope.clips(seq)[r['clip_ids'][0]][1]
assert music['source_start']==0 and music['timeline_end']==seq['duration']
print('non_caption_preservation',True,'room',room,flush=True)
