import pytest
import asyncio
from app.services import voice_codex as vc


@pytest.mark.asyncio
@pytest.mark.parametrize('intentional', [True, False])
@pytest.mark.parametrize('event', [
    {'method': 'process/closed'},
    {'method': 'turn/completed', 'params': {'turn': {'status': 'interrupted'}}},
])
async def test_process_ending_is_cancellation_only_after_explicit_close(intentional, event, caplog):
    entered = asyncio.Event()
    released = asyncio.Event()
    class Fake:
        thread_id = 'thread'
        turn_id = 'turn'
        async def rpc(self, *args): return {'turn': {'id': 'turn'}}
        async def receive(self):
            entered.set()
            await released.wait()
            return event
        def close(self): released.set()
    agent = vc.VoiceCodex()
    agent.owner = Fake()
    task = asyncio.create_task(agent.respond([{'role': 'user', 'content': 'test'}], [], ''))
    await asyncio.wait_for(entered.wait(), 1)
    if intentional:
        agent.close()
    else:
        released.set()
    try:
        with pytest.raises(asyncio.CancelledError if intentional else RuntimeError):
            await asyncio.wait_for(task, 1)
        assert ('voice_backend_exception' in caplog.text) is not intentional
        assert agent.closed
        assert not agent.active
    finally:
        agent.close()

def test_image_stays_visual_on_reused_conversation():
    packed=vc.pack([{'role':'user','content':[{'type':'input_image','image_url':'data:image/png;base64,AAAA'}]}])
    assert packed[1]=={'type':'image','url':'data:image/png;base64,AAAA'}
    assert 'AAAA' not in packed[0]['text']

@pytest.mark.asyncio
async def test_tool_continuation_and_next_message_reuse_thread(monkeypatch):
    instances=[]
    class Fake:
        def __init__(self):
            instances.append(self);self.thread_id='t';self.sent=[];self.closed=False
            self.events=[{'method':'item/tool/call','id':8,'params':{'tool':'check_dan_status','arguments':{}}}]
        async def start(self,*args,**kw): self.config=kw;self.model=args[3]
        async def receive(self):return self.events.pop(0)
        async def rpc(self,method,params):
            assert method=='turn/start' and params['threadId']=='t'
            return {'turn':{'id':'next'}}
        def send(self,x):self.sent.append(x)
        def close(self):self.closed=True
    monkeypatch.setattr(vc,'CodexTurn',Fake)
    agent=vc.VoiceCodex()
    try:
        first=await agent.respond([{'role':'user','content':'状況は？'}],[],'rule')
        call=first['output'][0]
        owner=instances[0]
        done=[{'method':'item/completed','params':{'item':{'type':'agentMessage','text':'作業中です','phase':'final_answer'}}},
              {'method':'turn/completed','params':{'turn':{'status':'completed'}}}]
        owner.events=list(done)
        await agent.respond([{'type':'function_call_output','call_id':call['call_id'],'output':'running'}],[],'rule')
        assert owner.sent[0]['id']==8 and not owner.closed
        owner.events=list(done)
        await agent.respond([{'role':'user','content':'次は？'}],[],'rule')
        assert len(instances)==1 and owner.model=='gpt-6-astra'
    finally:agent.close()
    assert owner.closed

@pytest.mark.asyncio
async def test_orphan_result_never_reexecutes(monkeypatch):
    monkeypatch.setattr(vc,'CodexTurn',lambda:pytest.fail('must not launch'))
    with pytest.raises(ValueError):
        await vc.VoiceCodex().respond([{'type':'function_call_output','call_id':'old','output':'bought'}],[],'')

@pytest.mark.asyncio
async def test_error_log_records_cause_without_tool_contents(monkeypatch, caplog):
    class Fake:
        thread_id='thread';turn_id='turn'
        def close(self):pass
    agent=vc.VoiceCodex();agent.owner=Fake();agent.pending=('expected',8)
    with pytest.raises(ValueError):
        await agent.respond([{'type':'function_call_output','call_id':'wrong','output':'SECRET_PAYMENT_DATA'}],[],'')
    assert 'voice_backend_exception' in caplog.text and 'expected' in caplog.text
    assert 'SECRET_PAYMENT_DATA' not in caplog.text

@pytest.mark.asyncio
async def test_steering_keeps_pending_tool_and_reads_ack():
    class Fake:
        thread_id='thread';turn_id='turn'
        async def request_concurrent(self,method,params):
            assert method=='turn/steer' and params['expectedTurnId']=='turn'
            return {'result':{'turnId':'turn'}}
    agent=vc.VoiceCodex();agent.owner=Fake();agent.active=True;agent.pending=('call',8)
    assert await agent.steer([{'role':'user','content':'stop'}])
    assert agent.pending==('call',8)

@pytest.mark.asyncio
async def test_only_final_answer_text_is_streamed_not_worker_commentary():
    class Fake:
        thread_id='thread';turn_id='turn'
        def __init__(self):
            self.events=[
                {'method':'item/started','params':{'item':{'type':'agentMessage','id':'c','phase':'commentary'}}},
                {'method':'item/agentMessage/delta','params':{'itemId':'c','delta':'調べます'}},
                {'method':'item/started','params':{'item':{'type':'agentMessage','id':'f','phase':'final_answer'}}},
                {'method':'item/agentMessage/delta','params':{'itemId':'f','delta':'記録を確認しました。'}},
                {'method':'item/completed','params':{'item':{'type':'agentMessage','id':'f','phase':'final_answer','text':'記録を確認しました。'}}},
                {'method':'turn/completed','params':{'turn':{'status':'completed'}}},
            ]
        async def rpc(self,*a):return {'turn':{'id':'turn'}}
        async def receive(self):return self.events.pop(0)
        def close(self):pass
    agent=vc.VoiceCodex();agent.owner=Fake();text=[]
    try:
        result=await agent.respond([{'role':'user','content':'確認して'}],[],'',on_text=text.append)
        assert text==['記録を確認しました。']
        assert result['output'][0]['content'][0]['text']==text[0]
    finally:agent.close()

@pytest.mark.asyncio
async def test_new_request_recovers_but_orphan_tool_never_replays(monkeypatch):
    from app.services import voice_live as live
    class Dead:
        closed=True
        async def respond(self,*a):raise ValueError('closed')
        def close(self):pass
    class Fresh:
        closed=False
        async def respond(self,items,*a):return {'output':[], 'received':items}
        def close(self):pass
    live.register('recovery-test','owner','rules',[])
    state=live._sessions['recovery-test'];state['agent']=Dead()
    monkeypatch.setattr(live,'VoiceCodex',Fresh)
    try:
        with pytest.raises(ValueError):
            await live.respond('recovery-test','owner',[{'type':'function_call_output','call_id':'paid','output':'done'}])
        assert isinstance(state['agent'],Dead)
        answer=await live.respond('recovery-test','owner',[{'role':'user','content':'状況だけ調べて'}])
        assert isinstance(state['agent'],Fresh) and answer['received'][0]['content']=='状況だけ調べて'
    finally:live.close('recovery-test','owner')
