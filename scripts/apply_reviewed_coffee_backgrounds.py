"""Apply the reviewed four Omni 1.1 backgrounds with baseline and scope checks."""
import copy
import json
import shutil
import time
from pathlib import Path
from app.services import timeline_draft as td, timeline_live as tl, timeline_commands as tc
from app.services.timeline_scope import make_scope, violations
from app.services.editor_project import update_work

room='a3970e0b-f7dc-472e-ad63-e8c51382ddb3'
cid='a65ccfdd-6304-4dee-9fa4-c06d79ab921c'
test_room='editor-omni-input-038e08e1'
_, reviewed=tl.live_sequence(test_room,'d2a7066c180940f58269f576c9986d7b')
baseline=td.load_draft(test_room,'84dda6de4c5a')['base_sequence']
draft=td.create_draft(room,cid,'reviewed-omni-1.1-recovery')
assert draft['base_hash']==td.sequence_hash(baseline),'Live edits changed; review before applying'
ids={'clip_ag_v_0c6074d1fe','clip_ag_v_0c9be879d0','clip_ag_v_fb27b15a6f','clip_ag_v_1ba49bd557'}
replacements={c['id']:c for t in reviewed['tracks'] for c in t['clips'] if c['id'] in ids}
assert len(replacements)==4
for track in draft['sequence']['tracks']:
    track['clips']=[copy.deepcopy(replacements.get(c['id'],c)) for c in track['clips']]
draft['edit_scope']=make_scope(baseline,list(ids))
assert not violations(baseline,draft['sequence'],draft['edit_scope'])
assets=tl._assets(test_room)
p=td._room_dir(room)
backup=p/'recovery'/f'before-omni-backgrounds-{int(time.time())}.json'
backup.parent.mkdir(exist_ok=True)
with td.ContentsLock(room):
    backup.write_text(json.dumps(td._read_contents_raw(room),ensure_ascii=False),encoding='utf-8')
    destination=tl._assets(room)
    for c in replacements.values():
        asset=copy.deepcopy(assets[c['asset_id']])
        assert asset['metadata']['duration']>0
        assert Path(asset['local_path']).is_file()
        destination[asset['id']]=asset
    out=p/'assets.json';tmp=out.with_suffix('.json.recovery.tmp')
    tmp.write_text(json.dumps(list(destination.values()),ensure_ascii=False),encoding='utf-8');tmp.replace(out)
td.save_draft(draft)
result=td.commit_draft(room,draft['draft_id'],lambda s,r:tc.validate_sequence(s,tl._assets(r),asset_dir=str(p)))
assert result['ok'],result
update_work(room,cid,'voice_and_motion_overhaul','背景4カットは映像化済み・HeyGen音声は接続待ち','blocked','Omni 1.1で背景を生成・検品して反映済み。HeyGenは使うアカウントの確認待ち。音声は未変更。')
update_work(room,cid,'heygen_account','HeyGenの本人音声を準備','blocked','使うHeyGenアカウントの確認待ちです。保存済みの接続情報がなく、ブラウザーも未ログインでした。音声の生成・差し替えはまだ完了していません。')
shutil.copy2(td._room_dir(test_room)/'review/four-backgrounds-reviewed_sequence.mp4','uploads/editor-recovery-check/coffee-omni-1.1.mp4')
print(json.dumps({'ok':True,'draft_id':draft['draft_id'],'backup':str(backup),'changed_clips':sorted(ids),'voice_changed':False}))
