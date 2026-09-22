import json

import httpx
import pytest

from scripts.voice_jev_eval import CASES, QUESTIONS, evaluate, payload, summary


def case():
    return json.loads(CASES.read_text(encoding='utf-8'))[0]


def response():
    c = case()
    return {'model':'jev-latest','answers':{
        k:{'type':'choice','choice':c['expected'][k][0],'confidence':.8,
           'probabilities':{option:float(option==c['expected'][k][0]) for option in q['criteria']}}
        for k,q in QUESTIONS.items()},'usage':{'input_tokens':100,'output_tokens':20}}


def test_labels_are_not_sent_to_model():
    p = payload(case())
    assert 'expected' not in p and 'case_id' not in p
    assert p['state'] == case()['state']

def test_encoding_loss_is_rejected_before_api_call():
    c=case();c['state']['latest_user']='??????'
    with pytest.raises(ValueError,match='encoding loss'):payload(c)

def test_japanese_fixture_content_is_intact():
    import re
    for c in json.loads(CASES.read_text(encoding='utf-8')):
        payload(c)
        assert re.search('[\u3040-\u9fff]',c['state']['latest_user'])


@pytest.mark.asyncio
async def test_records_accuracy_and_probabilities():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=response()))) as client:
        row=await evaluate(client,'secret-test-key',case())
    assert row['status']=='ok' and all(row['matches'].values())
    assert 'secret-test-key' not in json.dumps(row)


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[401,429,529])
async def test_failure_is_not_retried_or_exposed(status):
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(status,json={'error':'PRIVATE_TRANSCRIPT'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        row=await evaluate(client,'secret-test-key',case())
    assert len(requests)==1 and row['status']=='unavailable'
    assert 'PRIVATE_TRANSCRIPT' not in json.dumps(row)
    assert summary([row])['unavailable']==1


@pytest.mark.asyncio
async def test_timeout_returns_unavailable():
    def handler(request):raise httpx.ReadTimeout('private upstream detail',request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        row=await evaluate(client,'secret',case())
    assert row['status']=='unavailable' and 'private' not in json.dumps(row)


@pytest.mark.asyncio
async def test_invalid_distribution_is_rejected():
    data=response();data['answers']['speech']['probabilities']['pause']=float('nan')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,content=json.dumps(data)))) as client:
        row=await evaluate(client,'secret',case())
    assert row['status']=='unavailable'
