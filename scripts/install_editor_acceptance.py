"""Make the tested new-topic movie accessible in the user's normal production room."""
import copy,json,time
from app.services import timeline_draft as td,timeline_live as tl,timeline_commands as tc
from app.api.production_asset_routes import _read_assets,_write_assets

source='assistant-complete-test-8e96bdba'
target='a3970e0b-f7dc-472e-ad63-e8c51382ddb3'
cid='a65ccfdd-6304-4dee-9fa4-c06d79ab921c'
content,seq=tl.live_sequence(source,cid)
content=copy.deepcopy(content)
content.update(title='朝の珈琲店｜制作テスト',room_id=target,status='ready')
content['editor_work']=[{'id':'acceptance','title':'相談・下書き制作・音声修正・書き出しの動作確認','status':'done'}]
content['acceptance_origin']={'room_id':source,'content_id':cid}
assets=_read_assets(target);known={a['id'] for a in assets}
source_assets=tl._assets(source)
ids={c.get('asset_id') for t in seq['tracks'] for c in t['clips']} - {None}
for aid in ids-known:
    a=copy.deepcopy(source_assets[aid]);a['room_id']=target;assets.append(a)
assert not tc.validate_sequence(seq,{a['id']:a for a in assets},asset_dir=str(td._room_dir(target)))
_write_assets(target,assets)
with td.ContentsLock(target):
    contents=td._read_contents_raw(target)
    assert not any(c['id']==cid for c in contents),'Already installed; do not overwrite user edits'
    contents.append(content);td._write_contents_raw(target,contents)
print('INSTALLED',target,cid,content['title'])
