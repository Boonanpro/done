"""Real CLI acceptance; isolated timeline, no paid media generation."""
import asyncio
import json
import time
import uuid
from types import SimpleNamespace
from app.api import editor_assistant_routes as api
from app.services import editor_codex as cli,editor_reasoning as reasoning,timeline_draft as td,timeline_scope as scope


async def steering():
    key=('acceptance',uuid.uuid4().hex);seen=[];sent=False;start=time.monotonic()
    async for e in cli.stream_response([{'role':'user','content':'100から10000までの素数の一覧を計算して説明してください。ファイルは変更しないでください。'}],[],
            '日本語で答える。ユーザーの後の訂正・取消を優先する。', 'gpt-6-astra',run_key=key):
        if e['type']=='progress' and e.get('phase')=='thinking' and not sent:
            assert cli.steer_active(key,'直前の依頼は取り消します。素数は調べなくて良いです。「取り消しました」とだけ返答してください。')
            sent=True
        if e['type']=='text':seen.append(e['delta'])
        if e.get('phase')=='update_failed':raise AssertionError(e)
    assert sent and '取り消' in ''.join(seen),seen
    assert key not in cli._active
    print('STEER',json.dumps({'seconds':round(time.monotonic()-start,2),'reply':''.join(seen)},ensure_ascii=False),flush=True)


async def scale():
    room='voice-repair-test-'+uuid.uuid4().hex[:8];folder=td._room_dir(room);folder.mkdir(parents=True)
    for f in ('contents.json','assets.json'):(folder/f).write_text('[]')
    api._get_user=lambda _:SimpleNamespace(user_id='acceptance')
    cid=api.new_content(None,api.NewContent(room_id=room))['content_id']
    seq={'duration':120,'format':'16:9','tracks':[{'id':str(k),'type':'video','clips':[]} for k in range(3)]}
    for i in range(12):
        seq['tracks'][0]['clips'].append({'id':f'bg{i}','style':'solid','region':{'x':.1,'y':.1,'width':.4,'height':.3},'timeline_start':i*10,'timeline_end':i*10+10})
        for k in (1,2):seq['tracks'][k]['clips'].append({'id':f'text{k}_{i}','text':'見出し' if k==1 else '案内する内容','style':{'x':.15,'y':.15+k*.05,'fontSize':.8,'maxWidth':.3},'timeline_start':i*10,'timeline_end':i*10+10})
    contents=td._read_contents_raw(room);contents[0]['timeline']['sequence']=seq;td._write_contents_raw(room,contents)
    ids=list(scope.clips(seq));phrase='左上の案内を、黒い背景も文字も含めて、左上の角の位置は変えずに、全体を80％に縮小してください。表示されているすべての区間を同じように直してください。'
    begun=api.begin(None,api.Context(room_id=room,content_id=cid,input_mode='voice',live_dialogue=[{'role':'user','text':phrase}]))
    inputs=reasoning.initial_input(begun['context'],[]);tools=reasoning.tools_for_conversation(api.EDITOR_TOOLS)
    started=time.monotonic();calls=[];saved=None
    for _ in range(12):
        complete=None
        async for e in reasoning.stream_response(inputs,tools,live=True):
            if e['type']=='completed':complete=e
        assert complete
        inputs.extend(complete['output'])
        pending=[o for o in complete['output'] if o['type']=='function_call']
        if not pending:break
        for c in pending:
            assert c['name']!='execute_work','Simple scale unnecessarily delegated'
            calls.append(c['name'])
            result=await api.tool(None,api.ToolRequest(room_id=room,turn_id=begun['turn_id'],name=c['name'],args=json.loads(c['arguments'])))
            if result.get('committed'):saved=time.monotonic()-started
            image=result.pop('image',None)
            inputs.append({'type':'function_call_output','call_id':c['call_id'],'output':json.dumps(result,ensure_ascii=False)})
            if image:inputs.append({'role':'user','content':[{'type':'input_image','image_url':image}]})
    after=scope.clips(td._content_sequence(td._read_contents_raw(room)[0]))
    assert saved is not None
    for i in range(12):
        assert abs(after[f'bg{i}'][1]['region']['width']-.32)<1e-6
        assert abs(after[f'text1_{i}'][1]['style']['fontSize']-.64)<1e-6
    print('SCALE',json.dumps({'room':room,'content_id':cid,'saved_seconds':round(saved,2),'total_seconds':round(time.monotonic()-started,2),'calls':calls},ensure_ascii=False),flush=True)


async def main():
    await steering()
    await scale()

if __name__=='__main__':asyncio.run(main())
