"""Durable instructions delivered to a running production worker at tool boundaries."""
import json,time,uuid
from app.services import timeline_draft as td

def submit(room,job_id,instruction,clip_ids=None):
    folder=td._room_dir(room)/'jobs'/job_id/'instructions'
    folder.mkdir(parents=True,exist_ok=True)
    item={'id':uuid.uuid4().hex,'at':time.time(),'instruction':instruction,'clip_ids':clip_ids or []}
    dest=folder/(item['id']+'.json');tmp=dest.with_suffix('.tmp')
    tmp.write_text(json.dumps(item,ensure_ascii=False),encoding='utf-8');tmp.replace(dest)
    # A redirected job must not remain blocked on its previous question. Deliver
    # the actual new instruction as the response, never manufacture an approval.
    from app.services import editor_questions
    question = editor_questions.read(room, job_id)
    if question:
        try:
            editor_questions.answer(room, job_id, question['id'],
                'ユーザーから作業への追加・変更指示です。これは購入や生成への一律の承認ではありません。最新の指示に従って質問の必要性を再判断してください。\n' + instruction)
        except ValueError:
            pass  # Another response already resolved it.
    return item

def pending(room,job_id):
    folder=td._room_dir(room)/'jobs'/job_id/'instructions'
    rows=[]
    for p in folder.glob('*.json'):
        if p.with_suffix('.received').exists():continue
        try:rows.append(json.loads(p.read_text(encoding='utf-8')))
        except (OSError,ValueError):continue
    return sorted(rows,key=lambda x:x['at'])

def receive(room,job_id):
    rows=pending(room,job_id)
    for row in rows:
        (td._room_dir(room)/'jobs'/job_id/'instructions'/(row['id']+'.received')).write_text(str(time.time()))
    return rows
