"""Shared runtime asks a question, resumes, and remembers only its editor thread."""
import copy,json,time,uuid
from concurrent.futures import ThreadPoolExecutor
from app.services import timeline_draft as td,timeline_live as tl,editor_questions
from app.services.timeline_agent import run_timeline_agent

r='editor-dialogue-'+uuid.uuid4().hex[:8];cid=uuid.uuid4().hex;job=uuid.uuid4().hex
source,_=tl.live_sequence('assistant-complete-test-8e96bdba','a65ccfdd-6304-4dee-9fa4-c06d79ab921c')
c=copy.deepcopy(source);c['id']=cid;p=td._room_dir(r);p.mkdir(parents=True,exist_ok=True)
(p/'contents.json').write_text(json.dumps([c],ensure_ascii=False),encoding='utf-8')
(p/'assets.json').write_text(json.dumps(list(tl._assets('assistant-complete-test-8e96bdba').values()),ensure_ascii=False),encoding='utf-8')
def run(text,job):
    return run_timeline_agent(room_id=r,user_id='2582a188-ff24-4a4f-b989-6063034d90b2',content_id=cid,job_id=job,
        preparation_only=True,instruction=text,on_event=lambda e:print(e.get('type'),e.get('name',''),str(e.get('text',''))[:100],flush=True) if e.get('type')!='keepalive' else None)
print('ROOM',r,flush=True)
with ThreadPoolExecutor(max_workers=1) as pool:
    f=pool.submit(run,'接続の実地テストです。ask_userで「テスト用の合言葉を教えてください」と質問し、回答を受け取ったらその言葉を確認してreport_resultで達成を記録してください。外部サービスや動画には変更を加えません。',job)
    deadline=time.monotonic()+180
    q=None
    while time.monotonic()<deadline and not f.done():
        q=editor_questions.read(r,job)
        if q:break
        time.sleep(.5)
    assert q,'No question reached editor'
    editor_questions.answer(r,job,q['id'],'青い珈琲カップ')
    result=f.result(timeout=180)
    assert result['ok'] and not result['committed'] and '青い' in result['summary'],result
second=run('さっき私が答えたテスト用の合言葉は？一文で答え、report_resultに記録してください。作業や調査は不要です。',uuid.uuid4().hex)
assert second['ok'] and '青い珈琲カップ' in second['summary'],second
assert tl.live_sequence(r,cid)[1]==td._content_sequence(c)
print('PASS question -> answer -> continuation -> isolated editor memory; timeline unchanged',flush=True)
