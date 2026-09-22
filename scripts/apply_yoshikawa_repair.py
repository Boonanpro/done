"""Apply the reviewed isolated repair only if the real movie is still its base."""
import json,copy,time
from app.services import timeline_draft as td,timeline_live as tl,timeline_commands as tc,timeline_scope as scope
from app.api.production_asset_routes import _read_assets,_write_assets

room='a3970e0b-f7dc-472e-ad63-e8c51382ddb3'
review='yoshikawa-repair-4e31fca0'
cid='277f96d8-2609-43e9-ba18-bcf3ea37f576'
folder=td._room_dir(room)
base=json.loads((td._room_dir(review)/'repair-base.json').read_text(encoding='utf-8'))
_,repaired=tl.live_sequence(review,cid)
_,live=tl.live_sequence(room,cid)
assert td.sequence_hash(live)==td.sequence_hash(base),'User movie changed since review; do not overwrite'
new_assets=tl._assets(review)
# Remove an existing 0.01s overlap at the repaired ending's entry.
c=scope.clips(repaired)['clip_ag_audio_e7e4aae4e5'][1]
assert abs(c['timeline_end']-149.71)<.001
c['source_end']-=.01;c['timeline_end']=149.7
problems=tc.validate_sequence(repaired,new_assets,asset_dir=str(td._room_dir(review)))
assert not problems,problems
assert repaired['format']==base['format']=='16:9'
assert not scope.violations(base,repaired)
backup=folder/'recovery'/f'before-reviewed-repair-{int(time.time())}.json'
backup.parent.mkdir(exist_ok=True)
backup.write_text(json.dumps(td._read_contents_raw(room),ensure_ascii=False),encoding='utf-8')
assets=_read_assets(room)
if not any(a['id']=='recovered_reference_parts' for a in assets):
    a=copy.deepcopy(new_assets['recovered_reference_parts']);a['room_id']=room
    assets.append(a);_write_assets(room,assets)
d=td.create_draft(room,cid)
assert d['base_hash']==td.sequence_hash(base)
d['sequence']=repaired
d['log'].append({'t':time.time(),'tool':'reviewed_repair','args':{'review_room':review,'backup':str(backup)}})
td.save_draft(d)
result=td.commit_draft(room,d['draft_id'],lambda s,r:tc.validate_sequence(s,tl._assets(r),asset_dir=str(folder)))
assert result['ok'],result
print('APPLIED',d['draft_id'],str(backup),tl.describe_changes(base,repaired))
