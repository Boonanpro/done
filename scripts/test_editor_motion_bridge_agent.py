"""Real production-agent partial source-edit acceptance in an isolated room."""
import copy,json,uuid
from pathlib import Path
from app.services import timeline_draft as td
from app.services.timeline_agent import run_timeline_agent
from app.api.production_asset_routes import _append_job_event
state=json.loads(Path('uploads/motion-bridge-test.json').read_text());r=state['room_id'];cid=state['content_id'];job=uuid.uuid4().hex
before=copy.deepcopy(state['before'])
def emit(e):
 _append_job_event(r,job,e)
 print(e.get('type'),str(e.get('text',''))[:160],flush=True)
result=run_timeline_agent(room_id=r,user_id='2582a188-ff24-4a4f-b989-6063034d90b2',content_id=cid,job_id=job,expected_hash=td.sequence_hash(before),
 instruction='この隔離した動画で最後に出る英語の「tell them」を「your idea」に直してください。文字以外の色、動き、尺とほかの場面はそのままで。新しい動画生成サービスへの課金は不要です。編集元が保存されているのでそこを直して見せてください。',on_event=emit)
p=td._room_dir(r);(p/'agent-result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
assert result['ok'] and result['committed'],result
after=td._content_sequence(td._read_contents_raw(r)[0])
assert before['format']==after['format']
oldclips={c['id']:c for t in before['tracks'] for c in t['clips']};newclips={c['id']:c for t in after['tracks'] for c in t['clips']}
assert set(oldclips)==set(newclips)
for id,c in oldclips.items():
 if id!=state['clip_id']: assert c==newclips[id], 'unrelated clip changed'
assets=json.loads((p/'assets.json').read_text(encoding='utf-8'));new=next(a for a in assets if a['id']==newclips[state['clip_id']]['asset_id'])
source=Path(new['metadata']['motion_source']['project_dir'])/'index.html'
assert 'your idea' in source.read_text(encoding='utf-8')
assert 'tell them' in (Path(state['source']['project_dir'])/'index.html').read_text(encoding='utf-8')
print('PASS: real agent changed source, rendered, committed and preserved other clip/original revision',flush=True)
