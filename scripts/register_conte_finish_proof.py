"""Create an isolated editable comparison timeline, leaving user projects untouched."""
import json,uuid,subprocess
from datetime import datetime,timezone
from pathlib import Path
from app.services import timeline_draft as td,timeline_commands as tc,timeline_live as tl
from app.services.editor_media import import_media
from app.services.timeline_context import native_exe_default

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'exports/conte-finish-proof'
ROOM='conte-finish-proof-20260924'
folder=td._room_dir(ROOM)
if (folder/'contents.json').exists():
    raise SystemExit('Comparison timeline already exists; preserving existing edits.')
sequence={'version':1,'format':'16:9','tracks':[]}
start=0; entries=[]
for filename,label,duration in [('motion-guide.mp4','動きの指定',6),('appearance.png','完成見た目',3),('guided.mp4','A：3D＋画像',6),('image_only.mp4','B：画像＋文章',6)]:
    result=import_media(ROOM,str(OUT/filename),label,origin='conte-finish-proof')
    assert result['ok'],result
    added=tc.add_clip(sequence,tl._assets(ROOM),asset_id=result['asset_id'],timeline_start=start,duration=duration,with_audio=result['metadata'].get('has_audio',False))
    assert added['ok'],added
    entries.append({'file':filename,'label':label,'start':start,'end':start+duration,'asset_id':result['asset_id']})
    start+=duration
errors=tc.validate_sequence(sequence,tl._assets(ROOM),asset_dir=str(folder))
assert not errors,errors
now=datetime.now(timezone.utc).isoformat();cid=str(uuid.uuid4())
content={'id':cid,'room_id':ROOM,'title':'動きと見た目を分ける制作比較','format':'16:9','status':'ready','asset_ids':[e['asset_id'] for e in entries],
         'timeline':{'format':'16:9','sequence':sequence},'created_at':now,'updated_at':now,
         'conte_source':{'scene_path':str(OUT/'scene.json'),'appearance_path':str(OUT/'appearance.png'),'entries':entries}}
with td.ContentsLock(ROOM):td._write_contents_raw(ROOM,[content])
(OUT/'timeline.json').write_text(json.dumps(content,ensure_ascii=False,indent=2),encoding='utf8')
exe=Path.home()/'.done/bin/native_ui_editor.exe'
(OUT/'open-editor.cmd').write_text('@echo off\r\nstart "" "'+str(exe)+'" "'+str(folder/'contents.json')+'" "'+str(folder)+'"\r\n',encoding='ascii')
check=subprocess.run([native_exe_default(),str(folder/'contents.json'),str(folder),'--dump-frame','1,10,16',str(OUT/'timeline-preview.png')],capture_output=True,text=True,timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
(OUT/'timeline-check.txt').write_text(check.stdout+'\n'+check.stderr,encoding='utf8')
check.check_returncode()
print(json.dumps({'room':ROOM,'content_id':cid,'validation_errors':errors,'timeline_seconds':start,'headless_exit':check.returncode}))
