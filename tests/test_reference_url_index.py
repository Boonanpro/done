import pytest
import asyncio
import json
import httpx
from app.services import reference_url_index as index

@pytest.mark.asyncio
async def test_availability_rejects_confirmed_failure_but_not_network_uncertainty(monkeypatch):
    real=httpx.AsyncClient
    def handle(request):
        url=request.url.params['url']
        return httpx.Response(403 if 'blocked' in url else 503 if 'uncertain' in url else 200)
    monkeypatch.setattr(index.httpx,'AsyncClient',lambda **kwargs:real(transport=httpx.MockTransport(handle),**kwargs))
    index._availability_cache.clear()
    rows=[{'id':k,'url':'https://www.youtube.com/watch?v='+k} for k in ('blocked','valid','uncertain')]
    assert await index.unavailable_reference_ids(rows)=={'blocked'}

def test_catalog_cache_reloads_atomic_replacement(tmp_path,monkeypatch):
    path=tmp_path/'videos.json'
    path.write_text(json.dumps({'references':[{'id':'old'}]}),encoding='utf8')
    monkeypatch.setattr(index,'INDEX',path)
    first=index.catalog()
    assert index.catalog() is first
    replacement=tmp_path/'next.json'
    replacement.write_text(json.dumps({'references':[{'id':'new'},{'id':'second'}]}),encoding='utf8')
    replacement.replace(path)
    assert index.catalog()==[{'id':'new'},{'id':'second'}]
    assert first==[{'id':'old'}]

@pytest.mark.asyncio
async def test_explicit_format_conflict_removed_from_results_and_shortlist(monkeypatch):
    monkeypatch.setattr(index,'candidates',lambda scope:[{'id':k,'search_text':k} for k in ('live_action','anime')])
    async def judge(user,state,questions,**kwargs):
        if 'reference' in questions:
            return {'available':True,'answers':{'reference':{'probabilities':{'live_action':.7,'anime':.3}}}}
        return {'available':True,'answers':{'live_action':{'probabilities':{'contradicted':.99}},'anime':{'probabilities':{'supported':.99}}}}
    monkeypatch.setattr(index.editor_jev,'judge',judge)
    result=await index.search('u','2D anime',verify_matches=True,discovery={'axis':'medium'})
    assert [r['id'] for r in result['results']]==['anime']
    assert [r['id'] for r in result['shortlist']]==['anime']

@pytest.mark.asyncio
async def test_known_unavailable_reference_is_not_offered(monkeypatch):
    monkeypatch.setattr(index,'candidates',lambda scope:[{'id':'private','search_text':'a','availability':'reported_unavailable'},{'id':'public','search_text':'b'}])
    async def judge(user,state,questions,**kwargs):
        assert 'private' not in questions['reference']['criteria']
        return {'available':True,'answers':{'reference':{'probabilities':{'public':1}}}}
    monkeypatch.setattr(index.editor_jev,'judge',judge)
    result=await index.search('u','request',embedded=True)
    assert result['results'][0]['id']=='public'

@pytest.mark.asyncio
async def test_large_catalog_has_bounded_fanout_and_final_choice_size(monkeypatch):
    rows=[{'id':str(n),'search_text':str(n)} for n in range(12000)]
    monkeypatch.setattr(index,'candidates',lambda scope:rows)
    active=0;peak=0;seen=set()
    async def judge(user,state,questions,**kwargs):
        nonlocal active,peak
        keys=list(questions['reference']['criteria'])
        assert len(keys)<=255
        active+=1;peak=max(peak,active)
        await asyncio.sleep(0)
        active-=1
        seen.update(set(keys)-{'none'})
        return {'available':True,'answers':{'reference':{'probabilities':{k:1/len(keys) for k in keys if k!='none'}}}}
    monkeypatch.setattr(index.editor_jev,'judge',judge)
    result=await index.search('u','request')
    assert len(seen)==12000 and peak<=4
    assert result['available'] and result['batch_count']==62

@pytest.mark.asyncio
async def test_router_keeps_secondary_genre_membership(monkeypatch):
    rows=[{'id':str(n),'labels':{'primary_genre':'other'}} for n in range(20)]
    rows += [{'id':'cross','labels':{'primary_genre':'other','genre_probabilities':{'film':.3}}},
             {'id':'a','labels':{'primary_genre':'launch'}},
             {'id':'b','labels':{'primary_genre':'film'}},
             {'id':'c','labels':{'primary_genre':'motion'}}]
    async def judge(*args,**kwargs):
        return {'available':True,'answers':{'genres':{'probabilities':{'launch':.5,'film':.3,'motion':.2}}}}
    monkeypatch.setattr(index.editor_jev,'judge',judge)
    selected,route=await index.route_candidates('u',rows,{})
    assert {r['id'] for r in selected}=={'cross','a','b','c'}
    assert route['mode']=='genres'

@pytest.mark.asyncio
async def test_router_uncertainty_keeps_every_row(monkeypatch):
    rows=[{'id':'a','labels':{'primary_genre':'launch'}}]
    async def judge(*args,**kwargs):
        return {'available':True,'answers':{'genres':{'probabilities':{'broad':.8,'launch':.2}}}}
    monkeypatch.setattr(index.editor_jev,'judge',judge)
    selected,route=await index.route_candidates('u',rows,{})
    assert selected==rows and route['mode']=='full'

@pytest.mark.asyncio
async def test_empty_routed_search_retries_full_index(monkeypatch):
    rows=[{'id':'narrow','search_text':'a'},{'id':'outside','search_text':'b'}]
    monkeypatch.setattr(index,'candidates',lambda scope:rows)
    async def route(*args,**kwargs):return rows[:1],{'mode':'genres','genres':['a']}
    monkeypatch.setattr(index,'route_candidates',route)
    async def judge(user,state,questions,**kwargs):
        keys=questions['reference']['criteria']
        return {'available':True,'answers':{'reference':{'probabilities':
            {'outside':1} if 'outside' in keys else {'none':1}}}}
    monkeypatch.setattr(index.editor_jev,'judge',judge)
    result=await index.search('u','request',routing='genres')
    assert result['results'][0]['id']=='outside'
    assert result['routing']['fallback']=='no_supported_result'

def test_observations_enrich_only_the_matching_reference(monkeypatch):
    base={'title':'Demo','publisher':'Publisher','labels':{'primary_genre':'launch','taste':[]},'description_excerpt':'A launch','url':'https://example.com'}
    monkeypatch.setattr(index,'catalog',lambda:[{**base,'id':'observed'},{**base,'id':'metadata'}])
    monkeypatch.setattr(index,'observations',lambda:{'observed':{'summary':'Actual cursor and UI, no live action'}})
    rows=index.candidates()
    assert 'Video observation: Actual cursor' in rows[0]['search_text']
    assert 'Video observation:' not in rows[1]['search_text']
    assert 'Model-observed' in index.presentation_rows()[0]['limitations'][0]
    assert 'Metadata-based' in index.presentation_rows()[1]['limitations'][0]

@pytest.mark.asyncio
async def test_every_candidate_is_searched_then_finalists_compared(monkeypatch):
    rows=[{'id':str(n),'search_text':str(n)} for n in range(1178)]
    monkeypatch.setattr(index,'candidates',lambda scope:rows)
    seen=[]
    async def judge(user,state,questions,**kwargs):
        keys=list(questions['reference']['criteria'])
        assert len(keys)<=255
        assert state['conversation']==[{'role':'user','text':'prior preference'}]
        assert state['displayed']==[{'id':'shown','title':'Previously shown look'}]
        seen.append(set(keys)-{'none'})
        return {'available':True,'answers':{'reference':{'probabilities':{k:1/(len(keys)-1) for k in keys if k!='none'}}}}
    monkeypatch.setattr(index.editor_jev,'judge',judge)
    result=await index.search('user','request',dialogue=[{'role':'user','text':'prior preference'}],displayed=[{'id':'shown','title':'Previously shown look'}])
    assert set.union(*seen[:6])=={r['id'] for r in rows}
    assert len(seen)==7
    assert result['available'] and result['batch_count']==6

@pytest.mark.asyncio
async def test_partial_failure_does_not_claim_full_coverage(monkeypatch):
    monkeypatch.setattr(index,'candidates',lambda scope:[{'id':str(n),'search_text':str(n)} for n in range(300)])
    async def judge(user,state,questions,**kwargs):
        if '299' in questions['reference']['criteria']:
            return {'available':False,'reason':'unavailable'}
        return {'available':True,'answers':{'reference':{'probabilities':{'0':1}}}}
    monkeypatch.setattr(index.editor_jev,'judge',judge)
    result=await index.search('user','request')
    assert not result['available']
    assert result['results']==[]


@pytest.mark.asyncio
async def test_content_and_availability_checks_overlap_and_both_filter(monkeypatch):
    import asyncio
    content_started=asyncio.Event()
    availability_started=asyncio.Event()
    rows=[{'id':k,'search_text':k} for k in ('wrong','blocked','good')]
    monkeypatch.setattr(index,'candidates',lambda scope:rows)
    async def judge(user,state,questions,**kwargs):
        if 'reference' in questions:
            return {'available':True,'answers':{'reference':{'probabilities':{'wrong':.4,'blocked':.35,'good':.25}}}}
        content_started.set()
        await asyncio.wait_for(availability_started.wait(),1)
        return {'available':True,'answers':{'wrong':{'probabilities':{'contradicted':1}}}}
    async def unavailable(rows):
        availability_started.set()
        await asyncio.wait_for(content_started.wait(),1)
        return {'blocked'}
    monkeypatch.setattr(index.editor_jev,'judge',judge)
    monkeypatch.setattr(index,'unavailable_reference_ids',unavailable)
    result=await index.search('u','reference',embedded=True,verify_matches=True)
    assert [r['id'] for r in result['results']]==['good']
    assert result['unavailable_ids']==['blocked']
