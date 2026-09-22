"""Decision boundaries must not turn uncertain taste feedback into edits."""
import pytest
from app.services import editor_visual_decision as router

async def raw_decide(*args, **kwargs):
    kwargs['verify_candidates']=False
    return await router.decide(*args, **kwargs)


@pytest.mark.asyncio
async def test_execution_records_are_available_to_the_decision_model(monkeypatch):
    monkeypatch.setattr(router.library,'catalog',lambda:[])
    async def judge(user,state,questions,**kwargs):
        assert state['execution_state']['active'][0]['status']=='running'
        return {'available':True,'answers':{'action':{'choice':'execute','probabilities':{'execute':1}}}}
    monkeypatch.setattr(router.editor_jev,'judge',judge)
    result=await raw_decide('u',[{'role':'user','text':'stop that job'}],execution_state={'active':[{'id':'job','status':'running'}]})
    assert result['needs_backend'] and result['action']=='execute'


@pytest.mark.asyncio
@pytest.mark.parametrize('disposition,expected',[('retain',True),('revise',False),('discard',False),('uncertain',False)])
async def test_pending_reference_survives_followup_only_when_semantically_retained(monkeypatch,disposition,expected):
    monkeypatch.setattr(router.library,'catalog',lambda:[{'id':'pending','title':'Existing film','family':'film'}])
    monkeypatch.setattr(router.library,'rank',lambda *a,**k:[])
    monkeypatch.setattr(router.library,'selection_description',lambda r:'film')
    async def judge(user,state,questions,**kwargs):
        assert state['pending_reference']['displayed'] is False
        assert state['pending_reference']['request']=='show a film'
        return {'available':True,'answers':{'action':{'choice':'talk','probabilities':{'talk':1}},
            'pending_disposition':{'choice':disposition,'probabilities':{disposition:1}}}}
    monkeypatch.setattr(router.editor_jev,'judge',judge)
    result=await raw_decide('u',[{'role':'user','text':'follow up'}],pending_reference={'text':'show a film','ids':['pending','unknown']})
    assert (result.get('reused_pending') is True)==expected
    assert result['selected_library_ids']==(['pending'] if expected else [])
    assert not result['needs_backend']


@pytest.mark.asyncio
async def test_failed_url_lookup_does_not_start_production_or_claim_coverage_gap(monkeypatch):
    from app.services import reference_url_index
    monkeypatch.setattr(router.library,'catalog',lambda:[])
    monkeypatch.setattr(reference_url_index,'presentation_rows',lambda:[])
    async def judge(*args,**kwargs):
        return {'available':True,'answers':{
          'consultation_next':{'choice':'compare','probabilities':{'compare':1}},
          'reference_level':{'choice':'work','probabilities':{'work':1}},
          'discovery_next':{'choice':'medium','probabilities':{'medium':1}}}}
    async def search(*args,**kwargs):return {'available':False,'results':[],'shortlist':[],'failure':{'reason':'timeout'}}
    monkeypatch.setattr(router.editor_jev,'judge',judge)
    monkeypatch.setattr(reference_url_index,'search',search)
    r=await router.decide('user',[{'role':'user','text':'もっと違う参考が見たい'}],include_url_index=True)
    assert r['handled'] and not r['needs_backend'] and not r['coverage_missing']
    assert r['discovery']['comparison']['reason']=='retrieval_failed'


@pytest.mark.asyncio
async def test_repeated_reference_does_not_split_selection_probability(monkeypatch):
    monkeypatch.setattr(router.library,'catalog',lambda:[])
    async def judge(user,state,questions,**kwargs):
        assert set(questions['target']['criteria']) == {'latest','other','revision','none'}
        assert len(state['displayed']) == 4  # Historical context is preserved.
        return {'available':True,'answers':{
            'action':{'choice':'select','probabilities':{'select':1}},
            'target':{'choice':'latest','confidence':1}}}
    monkeypatch.setattr(router.editor_jev,'judge',judge)
    items=[{'id':i,'library_id':lib,'reference_identity':lib,'title':title,'kind':'video'} for i,lib,title in
           [('old','reference','Look'),('latest','reference','Look'),('other','other','Another look')]]
    items.append({'id':'revision','library_id':'reference','reference_identity':'changed-visual','title':'Look','kind':'video'})
    result=await raw_decide('user',[{'role':'user','text':'Use the earlier look, but do not produce yet'}],items)
    assert result['action']=='select' and result['item_id']=='latest'
    assert result['handled'] and not result['needs_backend']


@pytest.mark.asyncio
async def test_shortlist_verification_recovers_second_requested_treatment_without_padding(monkeypatch):
    monkeypatch.setattr(router.library,'catalog',lambda:[
        {'id':x,'title':x,'description':x,'family':x} for x in ('a','b','rejected')])
    calls=[]
    async def judge(user,state,questions,**kwargs):
        calls.append(questions)
        if 'candidate' in questions:
            return {'available':True,'answers':{
                'action':{'choice':'compare','probabilities':{'compare':1}},
                'candidate':{'probabilities':{'a':.85,'rejected':.14,'b':.01,'none':0}},
                'count':{'choice':'2','probabilities':{'2':1}}}}
        return {'available':True,'answers':{
            'fit_a':{'score':2.7,'probabilities':{'3':.8,'2':.2}},
            'fit_b':{'score':2.6,'probabilities':{'3':.7,'2':.3}},
            'fit_rejected':{'score':.5,'probabilities':{'0':.5,'1':.5}},
            'count':{'choice':'2','probabilities':{'2':1}}}}
    monkeypatch.setattr(router.editor_jev,'judge',judge)
    result=await router.decide('user',[{'role':'user','text':'Compare two suitable treatments'}])
    assert result['selected_library_ids']==['a','b']
    assert len(calls)==2


@pytest.mark.asyncio
@pytest.mark.parametrize('probabilities,target,expected', [
    ({'compare': .54, 'select': .42, 'execute': .04}, 'shown', 'compare'),
    ({'compare': .42, 'select': .54, 'execute': .04}, 'shown', 'select'),
    ({'compare': .42, 'select': .54, 'execute': .04}, None, 'compare'),
    ({'compare': .73, 'select': .14, 'reveal': .1, 'talk': .03}, None, 'compare'),
    ({'select': .96, 'talk': .04}, None, 'talk'),
    ({'compare': .45, 'execute': .55}, None, None),
])
async def test_uncertainty_never_implies_edit_permission(monkeypatch, probabilities, target, expected):
    monkeypatch.setattr(router.library, 'catalog', lambda: [{'id':'a','title':'A','description':'example'}])
    monkeypatch.setattr(router.library, 'rank', lambda scores, rows, diverse, count: rows)
    monkeypatch.setattr(router.editor_jev, 'confident', lambda answer, allowed: target)
    async def judge(*args, **kwargs):
        return {'available':True,'answers':{
            'action':{'choice':max(probabilities,key=probabilities.get),'probabilities':probabilities},
            'destination':{'choice':'comparison','probabilities':{'comparison':1}},
            'fit_a':{'score':3},
        }}
    monkeypatch.setattr(router.editor_jev, 'judge', judge)
    result=await raw_decide('user',[{'role':'user','text':'a preference'}],[{'id':'shown','library_id':'a'}],retrieval='scores',verify_candidates=False)
    assert result['action']==expected
    assert result['needs_backend'] is False
    assert result['handled']==(expected is not None)


@pytest.mark.asyncio
async def test_missing_candidates_are_not_claimed_as_displayed(monkeypatch):
    monkeypatch.setattr(router.library, 'catalog', lambda: [])
    async def judge(*args, **kwargs):
        return {'available':True,'answers':{
            'action':{'choice':'compare','probabilities':{'compare':1}},
            'destination':{'choice':'comparison','probabilities':{'comparison':1}},
        }}
    monkeypatch.setattr(router.editor_jev, 'judge', judge)
    result=await raw_decide('user',[{'role':'user','text':'an unavailable look'}])
    assert result['coverage_missing']
    assert not result['handled']
    assert result['selected_library_ids']==[]


@pytest.mark.asyncio
async def test_ambiguous_process_feedback_does_not_start_research(monkeypatch):
    monkeypatch.setattr(router.library,'catalog',lambda:[])
    async def judge(*args,**kwargs):
        return {'available':True,'answers':{
            'action':{'choice':'compare','probabilities':{'compare':.57,'talk':.43,'execute':0}},
            'destination':{'choice':'comparison','probabilities':{'comparison':1}},
            'candidate':{'probabilities':{'none':1}},
        }}
    monkeypatch.setattr(router.editor_jev,'judge',judge)
    result=await raw_decide('user',[{'role':'user','text':'The way the examples are displayed is confusing.'}])
    assert result['action']=='talk' and result['handled']
    assert not result['needs_backend']


@pytest.mark.asyncio
async def test_choice_retrieval_preserves_words_and_avoids_per_candidate_questions(monkeypatch):
    monkeypatch.setattr(router.library, 'catalog', lambda: [
        {'id':'a','title':'A','description':'warm','family':'warm'},
        {'id':'b','title':'B','description':'cold','family':'cold'}])
    async def judge(user,state,questions,**kwargs):
        assert state['conversation']==[{'role':'user','text':'keep these exact words'}]
        assert not any(k.startswith('fit_') for k in questions)
        assert set(questions['candidate']['criteria'])=={'a','b','none'}
        return {'available':True,'answers':{
            'action':{'choice':'compare','probabilities':{'compare':1}},
            'destination':{'choice':'comparison','probabilities':{'comparison':1}},
            'candidate':{'probabilities':{'a':.8,'b':.1,'none':.1}},
        }}
    monkeypatch.setattr(router.editor_jev,'judge',judge)
    result=await raw_decide('user',[{'role':'user','text':'keep these exact words','observed_views':[{'unneeded':'trace'}]}])
    assert result['selected_library_ids']==['a']
    assert result['handled'] and not result['needs_backend']


@pytest.mark.asyncio
async def test_ranked_runner_up_is_not_automatically_an_eligible_comparison(monkeypatch):
    monkeypatch.setattr(router.library,'catalog',lambda:[
        {'id':x,'title':x,'description':x,'family':x} for x in ('clear','accent','rejected')])
    calls=[]
    async def judge(user,state,questions,**kwargs):
        calls.append(questions)
        assert 'exclude_rejected' in questions
        assert state['conversation'][0]['text']=='Compare two new looks; the old look is wrong'
        return {'available':True,'answers':{
                'action':{'choice':'compare','probabilities':{'compare':1}},
                'destination':{'choice':'comparison','probabilities':{'comparison':1}},
                'count':{'choice':'2','probabilities':{'2':1}},
                'candidate':{'probabilities':{'clear':.5,'accent':.2,'rejected':.3,'none':0}},
                'exclude_rejected':{'noul':.75}}}
    monkeypatch.setattr(router.editor_jev,'judge',judge)
    result=await raw_decide('user',[{'role':'user','text':'Compare two new looks; the old look is wrong'}],[{'id':'shown','library_id':'rejected'}])
    assert result['selected_library_ids']==['clear','accent']
    assert len(calls)==1


@pytest.mark.asyncio
async def test_scene_request_does_not_get_padded_with_old_caption_references(monkeypatch):
    monkeypatch.setattr(router.library,'catalog',lambda:[
        {'id':ident,'title':ident,'description':ident,'family':ident,'reference_role':role}
        for ident,role in [('caption','text'),('room','scene'),('sunset','scene')]])
    async def judge(*args,**kwargs):
        return {'available':True,'answers':{
            'action':{'choice':'compare','probabilities':{'compare':1}},
            'destination':{'choice':'comparison','probabilities':{'comparison':1}},
            'scope':{'choice':'scene','probabilities':{'scene':.98}},
            'count':{'choice':'1','probabilities':{'1':.9}},
            'candidate':{'probabilities':{'room':.5,'caption':.3,'sunset':.2,'none':0}}}}
    monkeypatch.setattr(router.editor_jev,'judge',judge)
    result=await raw_decide('user',[{'role':'user','text':'Now show an animated quiet interior'}])
    assert result['selected_library_ids']==['room']
