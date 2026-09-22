import asyncio
import httpx
import pytest
from app.services import editor_jev as j

@pytest.mark.asyncio
async def test_missing_key_and_timeout_preserve_fallback(monkeypatch):
    async def missing(_): return None
    monkeypatch.setattr(j, 'api_key', missing)
    result = await j.presentation_action('user', [], [{'id':'one','title':'A'}])
    assert result['handled'] is False and result['reason'] == 'not_configured'
    async def failed(_): raise httpx.ConnectError('private provider detail')
    monkeypatch.setattr(j, 'api_key', failed)
    result = await j.presentation_action('user', [], [{'id':'one','title':'A'}])
    assert result['handled'] is False and 'private' not in str(result)

@pytest.mark.asyncio
@pytest.mark.parametrize('action,target,confidence,handled',[
    ('reveal','one',.98,True),('play','one',.95,True),('pause','one',.99,True),
    ('delete','one',1,False),('play','unknown',1,False),('other','one',1,False),
    ('reveal','one',.6,False),('reveal','one',float('nan'),False)])
async def test_only_known_certain_view_actions(monkeypatch,action,target,confidence,handled):
    async def judge(user,state,questions):
        assert state['conversation'] == [{'role':'user','text':'原文'}]
        assert set(questions) == {'action','target'}
        return {'elapsed_ms':120,'answers':{
            'action':{'choice':action,'confidence':confidence},
            'target':{'choice':target,'confidence':confidence}}}
    monkeypatch.setattr(j,'judge',judge)
    result=await j.presentation_action('u',[{'role':'user','text':'原文'}],[{'id':'one','title':'A'}])
    assert result['handled'] is handled

@pytest.mark.asyncio
async def test_ranking_is_advisory_and_keeps_candidates(monkeypatch):
    async def judge(*args):return {'elapsed_ms':100,'answers':{'0':{'score':1},'1':{'score':3},'2':{'score':float('nan')}}}
    monkeypatch.setattr(j,'judge',judge)
    candidates=[{'url':'a'},{'url':'b'},{'url':'c'}]
    result=await j.rank_candidates('u',['test'],candidates)
    assert result['order']==[1,0]
    assert candidates==[{'url':'a'},{'url':'b'},{'url':'c'}]

@pytest.mark.asyncio
async def test_credential_is_not_sent_as_state_or_returned(monkeypatch):
    async def key(_):return 'secret-test-key'
    monkeypatch.setattr(j,'api_key',key)
    real_client=httpx.AsyncClient
    def respond(request):
        assert request.headers['authorization']=='Bearer secret-test-key'
        assert b'secret-test-key' not in request.content
        return httpx.Response(200,json={'answers':{},'usage':{'input_tokens':10}})
    monkeypatch.setattr(j.httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(respond)))
    result=await j.judge('u',{'text':'hello'}, {})
    assert result['available'] and 'secret-test-key' not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('statuses,headers,expected_calls,available',[
    ([529,200],{},2,True),([529,529],{},2,False),
    ([401],{},1,False),([429],{'retry-after':'20'},1,False),
    ([503],{'retry-after':'20'},1,False)])
async def test_transient_failure_has_one_bounded_retry(monkeypatch,statuses,headers,expected_calls,available):
    async def key(_):return 'secret'
    monkeypatch.setattr(j,'api_key',key)
    calls=[]
    def respond(request):
        status=statuses[len(calls)];calls.append(status)
        return httpx.Response(status,headers=headers,json={'answers':{}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(j,'client',lambda:client)
        result=await j.judge('user',{}, {},timeout=.5)
    assert len(calls)==expected_calls and result['available'] is available
    assert result['http_statuses']==calls
    assert result['elapsed_ms']<600
    assert 'secret' not in str(result)
