import pytest
from app.services import editor_discovery as discovery

def choice(value,p=1):return {'choice':value,'probabilities':{value:p}}

def test_uncertain_next_question_does_not_discard_known_user_preferences():
    plan=discovery.plan({'discovery_next':choice('focus',.3),
        'discovery_value_medium':choice('animation_3d'),'discovery_change':choice('pivot')})
    assert plan['beliefs']['medium']['preferred']=='animation_3d'
    assert plan['change']=='pivot' and not plan['progress_claim']
    # A new call has no sticky preference posterior or cross-project memory.
    changed=discovery.plan({'discovery_next':choice('focus'),
        'discovery_value_medium':choice('live'),'discovery_change':choice('pivot')})
    assert changed['beliefs']['medium']['preferred']=='live'
    assert changed['beliefs']['tone']['preferred'] is None

def test_next_question_cannot_repeat_a_settled_property():
    plan=discovery.plan({'discovery_next':{'choice':'tone','probabilities':{'tone':.7,'focus':.3}},
        'discovery_value_tone':choice('calm')})
    assert plan['next_axis']=='medium'

def test_overall_direction_cannot_choose_face_vs_hands():
    plan=discovery.plan({'discovery_next':choice('focus'),'discovery_level':choice('overall')})
    assert plan['next_axis'] in ('medium','tone','form','pace')
    detail=discovery.plan({'discovery_next':choice('focus'),'discovery_level':choice('detail')})
    assert detail['next_axis']=='focus'

@pytest.mark.asyncio
async def test_pair_requires_distinct_supported_sides_not_different_ids(monkeypatch):
    async def judge(user,state,questions,**kwargs):
        answers={k:choice('unknown') for k in questions}
        for ident in ('a','b'):
            answers['side_medium_'+ident]=choice('live')
            answers['fit_'+ident]={'score':3,'probabilities':{'3':1}}
        return {'available':True,'answers':answers}
    monkeypatch.setattr(discovery.editor_jev,'judge',judge)
    plan=discovery.plan({'discovery_next':choice('medium')})
    result=await discovery.select_pair('user',[],[{'id':'a'},{'id':'b'}],plan)
    assert result['ids']==[] and result['reason']=='insufficient_comparison_evidence'

@pytest.mark.asyncio
async def test_comparison_uses_available_unsettled_evidence(monkeypatch):
    async def judge(user,state,questions,**kwargs):
        answers={k:choice('unknown') for k in questions}
        for ident,side in [('a','live'),('b','animation_3d')]:
            answers['side_medium_'+ident]=choice(side)
            answers['fit_'+ident]={'score':3,'probabilities':{'3':1}}
        return {'available':True,'answers':answers}
    monkeypatch.setattr(discovery.editor_jev,'judge',judge)
    plan=discovery.plan({'discovery_next':choice('focus')})
    result=await discovery.select_pair('user',[],[{'id':'a'},{'id':'b'}],plan)
    assert result['ids']==['a','b'] and plan['next_axis']=='medium'
    assert [s['value'] for s in result['sides']]==['live','animation_3d']
