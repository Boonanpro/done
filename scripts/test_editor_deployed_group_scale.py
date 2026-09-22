"""Exercise the deployed HTTP -> CLI -> editor -> saved result path."""
import json,time
from pathlib import Path
import requests

base='http://localhost:8000/api/v1/editor-assistant'
room='voice-repair-test-bb882de5'
cid='db615289-f9c6-487a-92ca-bf2cfc1df063'
session=requests.Session()
session.headers['Authorization']='Bearer '+(Path.home()/'.done/native_token.txt').read_text().strip()

def post(path,data):
    r=session.post(base+path,json=data,timeout=60);r.raise_for_status();return r.json()

phrase='左上の案内を、背景と文字を含めて、左上の角を固定したまま今の50％にしてください。すべての表示区間を同じように修正してください。'
start=time.monotonic()
b=post('/begin',{'room_id':room,'content_id':cid,'input_mode':'voice',
    'live_dialogue':[{'role':'user','text':phrase}],
    'observed_views':[{'view':{'pointer':{'trail':'x'*41000}}}]})
assert b['context']['live_dialogue'][-1]['text']==phrase
outputs=[];calls=[];saved=None
for _ in range(20):
    response=session.post(base+'/reason',json={'room_id':room,'turn_id':b['turn_id'],'outputs':outputs,'runtime':{'voice_model':'gpt-live-1'}},stream=True,timeout=120)
    response.raise_for_status();pending=[];done=False
    for line in response.iter_lines():
        if not line:continue
        event=json.loads(line)
        assert event['type']!='error',event
        if event['type']=='tool':pending.append(event)
        if event['type']=='done':done=True;assert event['billing']=='chatgpt_plan'
    assert done
    if not pending:break
    outputs=[]
    for c in pending:
        assert c['name'] in {'timeline_state','read_conversation','project_status','read_skill','transform_visuals','timeline_frame','resolve_target','batch_edit'},c['name']
        calls.append(c['name'])
        result=post('/tool',{'room_id':room,'turn_id':b['turn_id'],'name':c['name'],'args':json.loads(c['arguments'])})
        if result.get('committed'):saved=time.monotonic()-start
        outputs.append({'call_id':c['call_id'],'result':result})
seq=json.loads((Path('uploads/production-assets')/room/'contents.json').read_text(encoding='utf-8'))[0]['timeline']['sequence']
regions=[c for t in seq['tracks'] for c in t['clips'] if 'region' in c]
assert len(regions)==12 and all(abs(c['region']['width']-.16)<1e-6 for c in regions)
assert saved is not None
print(json.dumps({'passed':True,'saved_seconds':round(saved,2),'total_seconds':round(time.monotonic()-start,2),'calls':calls},ensure_ascii=False))
