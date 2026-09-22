"""Actual ChatGPT-authenticated Codex -> editor tool -> saved caption -> reply.
Creates an isolated test room. Does not touch user timelines or API credits.
"""
import asyncio
import json
import time
import uuid
from types import SimpleNamespace
from app.api import editor_assistant_routes as api
from app.services import editor_reasoning as reasoning, timeline_draft as td, timeline_live as tl


async def main():
    room='codex-editor-test-'+uuid.uuid4().hex[:8]
    folder=td._room_dir(room);folder.mkdir(parents=True,exist_ok=True)
    for name in ('contents.json','assets.json'):(folder/name).write_text('[]')
    api._get_user=lambda _:SimpleNamespace(user_id='cli-test')
    cid=api.new_content(None,api.NewContent(room_id=room))['content_id']
    begun=api.begin(None,api.Context(room_id=room,content_id=cid,input_mode='voice',scope_mode='whole'))
    tools=[t for t in reasoning.tools_for_conversation(api.EDITOR_TOOLS) if t['name'] in ('batch_edit','timeline_frame','read_editor_context')]
    inputs=reasoning.initial_input(begun['context'],[{'role':'user','text':'3秒の字幕クリップを追加してください。文字は CLI接続確認。開始0秒、終了3秒。それ以外の制作や生成は不要です。実行してから結果を短く答えてください。'}])
    start=time.monotonic();backend=[];seen=[]
    for _ in range(8):
        completed=None
        async for event in reasoning.stream_response(inputs,tools,live=True):
            if event['type']=='text':print(event['delta'],end='',flush=True)
            if event['type']=='completed':completed=event;backend.append((event.get('backend'),event.get('billing')))
        assert completed
        inputs.extend(completed['output'])
        calls=[o for o in completed['output'] if o['type']=='function_call']
        if not calls:break
        for call in calls:
            seen.append(call['name']);args=json.loads(call['arguments'])
            if call['name']=='read_editor_context':result={'ok':True,**begun['context']}
            else:result=await api.tool(None,api.ToolRequest(room_id=room,turn_id=begun['turn_id'],name=call['name'],args=args))
            image=result.pop('image',None)
            inputs.append({'type':'function_call_output','call_id':call['call_id'],'output':json.dumps(result,ensure_ascii=False)})
            if image:inputs.append({'role':'user','content':[{'type':'input_image','image_url':image}]})
    _,seq=tl.live_sequence(room,cid)
    assert 'CLI接続確認' in json.dumps(seq,ensure_ascii=False),seq
    assert 'batch_edit' in seen
    assert all(b==('codex_cli','chatgpt_plan') for b in backend),backend
    print('\nPASS',json.dumps({'room':room,'content_id':cid,'seconds':round(time.monotonic()-start,2),'tools':seen,'backend':backend},ensure_ascii=False))


if __name__=='__main__':asyncio.run(main())
