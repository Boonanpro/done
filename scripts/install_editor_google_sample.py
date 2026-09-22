"""Publish the actual editor agent's tested B timeline in the user's room."""
import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from app.services import timeline_draft as td, timeline_commands as tc
from app.api.production_asset_routes import _read_assets

state=json.loads(Path('uploads/google-handoff-latest.json').read_text())
source=state['room_id'];target=state['source_room']
result=json.loads((td._room_dir(source)/'acceptance-result.json').read_text(encoding='utf-8'))
assert result['ok'] and result['committed']
content=copy.deepcopy(td._read_contents_raw(source)[0])
seq=td._content_sequence(content)
content.update(id=str(uuid.uuid4()),room_id=target,title='日本対ブラジル｜B・Omni完成見本',
               status='ready',created_at=datetime.now(timezone.utc).isoformat(),
               updated_at=datetime.now(timezone.utc).isoformat())
content['acceptance_origin']={'room_id':source,'job_id':state['job_id']}
content['editor_work']=[]
# Test-only reference additions are not part of the original user's work.
original=td._find_content(td._read_contents_raw(target),state['content_id'])
content['reference_ids']=original.get('reference_ids',[])
content['creative_brief']['constraints']='BはGoogle API直結で生成済み。Higgsfieldクレジットは使わない。追加の有料生成は今回の依頼と許可範囲を確認する。'
content['creative_brief']['feedback']='ユーザーはAよりBが高品質と評価。最後の場面の人物のちらつきは修正候補。'
ids={c.get('asset_id') for t in seq['tracks'] for c in t['clips']} - {None}
source_assets={a['id']:a for a in _read_assets(source)}
with td.ContentsLock(target):
    contents=td._read_contents_raw(target)
    assert not any(c.get('acceptance_origin',{}).get('job_id')==state['job_id'] for c in contents),'Already installed'
    assets=_read_assets(target);known={a['id'] for a in assets}
    for aid in ids-known:
        a=copy.deepcopy(source_assets[aid]);a['room_id']=target
        a.setdefault('metadata',{}).update(generator='google',model='gemini-omni-1.1-flash',
            reference_mode='style',receipt='D:/done/exports/omni-direct-comparison/b_from_reference.response.json')
        assets.append(a)
    assert not tc.validate_sequence(seq,{a['id']:a for a in assets},asset_dir=str(td._room_dir(target)))
    path=td._room_dir(target)/'assets.json';tmp=path.with_suffix('.google.tmp')
    tmp.write_text(json.dumps(assets,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
    contents.append(content);td._write_contents_raw(target,contents)
state['installed_content_id']=content['id']
Path('uploads/google-handoff-latest.json').write_text(json.dumps(state),encoding='utf-8')
print(json.dumps({'room_id':target,'content_id':content['id'],'title':content['title'],'duration':seq['duration']},ensure_ascii=False))
