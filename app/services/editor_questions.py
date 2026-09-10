"""A pending question belongs to a job, not to a disposable voice connection."""
import json,time,uuid,asyncio
from app.services import timeline_draft as td

def path(room,job):
    return td._room_dir(room)/'jobs'/job/'question.json'

def read(room,job):
    try:q=json.loads(path(room,job).read_text(encoding='utf-8'))
    except (OSError,ValueError):return None
    if (path(room,job).parent/(q['id']+'.answer.json')).exists():return None
    return q

def answer(room,job,question_id,text):
    with td.ContentsLock(room):
        q=read(room,job)
        if not q or q['id']!=question_id:raise ValueError('この質問にはすでに回答済みか、質問が更新されています')
        dest=path(room,job).parent/(q['id']+'.answer.json')
        tmp=dest.with_suffix('.tmp');tmp.write_text(json.dumps({'text':text,'at':time.time()},ensure_ascii=False),encoding='utf-8');tmp.replace(dest)

async def ask(room,job,text):
    p=path(room,job);p.parent.mkdir(parents=True,exist_ok=True)
    q={'id':uuid.uuid4().hex,'job_id':job,'text':text,'at':time.time()}
    with td.ContentsLock(room):
        tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(q,ensure_ascii=False),encoding='utf-8');tmp.replace(p)
    response=p.parent/(q['id']+'.answer.json')
    while True:
        if response.exists():return {'ok':True,'answer':json.loads(response.read_text(encoding='utf-8'))['text']}
        await asyncio.sleep(.5)
