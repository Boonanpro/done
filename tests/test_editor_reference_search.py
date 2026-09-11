import asyncio
import json
import pytest
from app.services import editor_reference_search as search

def html(vid='abcdefghijk'):
    return 'var ytInitialData = '+json.dumps({'contents':[{'videoRenderer':{'videoId':vid,'title':{'runs':[{'text':'Cafe'}]}}}]})+';'

def test_only_real_result_ids_and_deduplication():
    assert search.parse_results(html())[0]['url']=='https://www.youtube.com/watch?v=abcdefghijk'
    assert search.parse_results(html('https://evil.example'))==[]
    with pytest.raises(ValueError):search.parse_results('<html>Consent required</html>')

@pytest.mark.asyncio
async def test_parallel_search_collects_candidates_without_presenting_unreviewed_results(monkeypatch):
    shown=[];slow_finished=False
    class Response:
        def __init__(self,vid):self.text=html(vid)
        def raise_for_status(self):pass
    async def get(self,url,params):
        nonlocal slow_finished
        if params['search_query']=='slow':
            await asyncio.sleep(.1);slow_finished=True;return Response('lmnopqrstuv')
        return Response('abcdefghijk')
    def present(room,cid,items):
        shown.append((slow_finished,list(items)));return {'presentation':{'items':list(items)}}
    monkeypatch.setattr(search.httpx.AsyncClient,'get',get)
    monkeypatch.setattr(search,'present',present)
    result=await search.search('r','c',['fast','slow'])
    assert result['ok'] and len(result['candidates'])==2
    assert shown == []
    assert result['first_results_ms'] < result['elapsed_ms']

@pytest.mark.asyncio
async def test_canceled_search_cannot_change_presentation(monkeypatch):
    class Response:
        text=html()
        def raise_for_status(self):pass
    async def get(*args,**kwargs):return Response()
    monkeypatch.setattr(search.httpx.AsyncClient,'get',get)
    monkeypatch.setattr(search,'present',lambda *a:pytest.fail('canceled search published'))
    assert (await search.search('r','c',['cafe'],lambda:False))['canceled']


@pytest.mark.asyncio
async def test_web_search_uses_citations_and_expands_provider_redirect(monkeypatch):
    class Response:
        def raise_for_status(self):pass
        def json(self):
            return {'steps':[{'type':'model_output','content':[{'text':'A work, not a verified viewing.',
                'annotations':[{'type':'url_citation','title':'Artist','url':'https://vertexaisearch.cloud.google.com/grounding-api-redirect/example'}]}]}]}
        is_redirect=True
        headers={'location':'https://artist.example/film'}
    async def post(*a,**k):return Response()
    async def get(*a,**k):return Response()
    monkeypatch.setattr(search.httpx.AsyncClient,'post',post)
    monkeypatch.setattr(search.httpx.AsyncClient,'get',get)
    result=await search.search_web(['paper animation'])
    assert result['candidates'][0]['url']=='https://artist.example/film'
    assert result['candidates'][0]['inspection']=='search_only'
