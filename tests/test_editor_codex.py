import asyncio
import json

import pytest

from app.services import editor_codex as cli


@pytest.mark.parametrize('sandbox', ['read-only', 'workspace-write'])
def test_thread_uses_requested_filesystem_capability(sandbox):
    owner=object.__new__(cli.CodexTurn)
    calls=[]
    async def rpc(method,params):
        calls.append((method,params))
        if method=='account/read': return {'account':{'type':'chatgpt'}}
        if method=='thread/start': return {'thread':{'id':'thread'}}
        return {}
    owner.rpc=rpc;owner.send=lambda _:None
    asyncio.run(owner.prepare([], 'instructions', 'gpt-6-astra', sandbox=sandbox))
    config=next(p for m,p in calls if m=='thread/start')
    assert config['sandbox']==sandbox
    assert config['approvalPolicy']=='never'


def test_api_key_account_is_rejected_before_model_turn():
    owner=object.__new__(cli.CodexTurn)
    methods=[]
    async def rpc(method,params):
        methods.append(method)
        return {'account':{'type':'apiKey'}} if method=='account/read' else {}
    owner.rpc=rpc
    owner.send=lambda _:None
    with pytest.raises(RuntimeError,match='APIキー課金では実行しません'):
        asyncio.run(owner.start([],[],'instructions','gpt-6-astra'))
    assert methods==['initialize','account/read']


def test_tool_result_and_image_resume_the_same_cli_turn(monkeypatch,tmp_path):
    monkeypatch.delenv('DAN_EDITOR_SERVICE_TIER', raising=False)
    monkeypatch.setattr(cli.Path,'home',classmethod(lambda _:tmp_path))
    monkeypatch.setenv('CODEX_HOME',str(tmp_path/'.codex'))
    for name in ('hyperframes','hyperframes-creative','gsap-core'):
        skill=tmp_path/'.agents/skills'/name/'SKILL.md'
        skill.parent.mkdir(parents=True);skill.write_text('test knowledge')
    instances=[]
    class Fake:
        def __init__(self):
            self.thread_id='thread';self.sent=[];self.timer=None;self.closed=False
            self.events=[{'method':'item/tool/call','id':77,'params':{'tool':'timeline_frame','arguments':{'t':3}}}]
            instances.append(self)
        async def start(self,*args,**kwargs):self.config=kwargs['config_overrides']
        async def receive(self):return self.events.pop(0)
        def send(self,event):self.sent.append(event)
        def close(self):
            self.closed=True
            if self.timer:self.timer.cancel()
    monkeypatch.setattr(cli,'CodexTurn',Fake)
    async def collect(inputs):return [e async for e in cli.stream_response(inputs,[],'instructions','gpt-6-astra')]
    first=asyncio.run(collect([{'role':'user','content':'見せて'}]))[-1]
    call=first['output'][0]
    owner=instances[0]
    assert owner.config['features.shell_tool'] is False
    assert owner.config['features.fast_mode'] is True
    assert owner.config['service_tier']=='fast'
    assert 'model_reasoning_effort' in owner.config
    assert {cli.Path(s['path']).parent.name for s in owner.config['skills.config']}=={'hyperframes','hyperframes-creative'}
    assert all(s['enabled'] is False for s in owner.config['skills.config'])
    owner.events=[{'method':'item/agentMessage/delta','params':{'delta':'確認しました'}},
                  {'method':'item/completed','params':{'item':{'type':'agentMessage','text':'確認しました'}}},
                  {'method':'turn/completed','params':{'turn':{'status':'completed'}}}]
    second=asyncio.run(collect([call,{'type':'function_call_output','call_id':call['call_id'],'output':json.dumps({'ok':True})},
        {'role':'user','content':[{'type':'input_image','image_url':'data:image/png;base64,AAAA'}]}]))
    assert len(instances)==1 and owner.closed
    assert owner.sent[0]['id']==77
    assert owner.sent[0]['result']['contentItems'][1]=={'type':'inputImage','imageUrl':'data:image/png;base64,AAAA'}
    assert second[-1]['billing']=='chatgpt_plan'
    message = next(e for e in second if e['type']=='message_complete')
    assert message['text']=='確認しました'
    assert second.index(message)<len(second)-1


def test_lost_cli_tool_connection_is_not_replayed(monkeypatch):
    class Fake:
        closed=False
        def close(self):self.closed=True
        async def start(self,*args):raise AssertionError('must not replay tools')
    owner=Fake();monkeypatch.setattr(cli,'CodexTurn',lambda:owner)
    async def run():
        return [e async for e in cli.stream_response([{'type':'function_call_output','call_id':'codex-editor-expired','output':'{}'}],[],'','gpt-6-astra')]
    with pytest.raises(RuntimeError,match='実行済みの操作は再実行せず'):
        asyncio.run(run())
    assert owner.closed
