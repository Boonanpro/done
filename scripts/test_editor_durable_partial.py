"""Run the editor's default production model against an isolated real draft."""
import copy,json,uuid
from app.services import timeline_draft as td,timeline_live as tl
from app.services.timeline_agent import run_timeline_agent
from app.api.production_asset_routes import _append_job_event

r='editor-astra-'+uuid.uuid4().hex[:8];cid=uuid.uuid4().hex;job=uuid.uuid4().hex
source,_=tl.live_sequence('editor-durable-draft-6da96a6f','ef11c700-3dad-4954-a9bd-0414f5168b14')
content=copy.deepcopy(source);content['id']=cid
folder=td._room_dir(r);folder.mkdir(parents=True,exist_ok=True)
(folder/'contents.json').write_text(json.dumps([content],ensure_ascii=False),encoding='utf-8')
(folder/'assets.json').write_text(json.dumps(list(tl._assets('editor-durable-draft-6da96a6f').values()),ensure_ascii=False),encoding='utf-8')
seq=td._content_sequence(content)
caption=next(c for t in seq['tracks'] for c in t['clips'] if c.get('text'))
def emit(e):
    _append_job_event(r,job,e)
    print(e.get('type'),str(e.get('text',''))[:160],flush=True)
print('ROOM',r,flush=True)
result=run_timeline_agent(room_id=r,user_id='2582a188-ff24-4a4f-b989-6063034d90b2',content_id=cid,job_id=job,
    expected_hash=td.sequence_hash(seq),selected_clips=[{'id':caption['id']}],on_event=emit,
    instruction=f"隔離した制作テストです。字幕 {caption['id']} の文言だけを『情報を揃えて、スムーズに。』へ変えてください。位置・尺・サイズなど他の属性と他クリップは保持。素材生成や外部サービス操作は不要です。timelineツールで編集・検証し、実行結果を一文で報告してください。")
(folder/'result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
assert result['ok'] and result['committed'],result
_,after=tl.live_sequence(r,cid)
expected=copy.deepcopy(seq)
next(c for t in expected['tracks'] for c in t['clips'] if c['id']==caption['id'])['text']='情報を揃えて、スムーズに。'
assert after==expected,'Unexpected edit outside requested text'
print('PASS Astra default executed and committed only requested caption',flush=True)
