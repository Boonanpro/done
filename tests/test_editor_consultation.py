import pytest
from app.services import editor_consultation as memo, editor_visual_decision as router, reference_url_index

def answer(value):return {'choice':value,'probabilities':{value:1}}


def test_proactive_actions_are_available_to_the_actual_judge():
    questions=memo.questions([],{'version':2,'facts':{}})
    choices=questions['consultation_next']['criteria']
    assert {'ask','propose','compare','conversation','execute'} <= choices.keys()

def test_evidence_cannot_be_invented_or_taken_from_assistant():
    dialogue=[{'role':'assistant','text':'Use comedy?'},{'role':'user','text':'I want a film'}]
    result=memo.update(None,dialogue,{'memo_brief':answer('1'),'memo_direction':answer('0')})
    assert result['facts']=={'brief':['I want a film']}
    assert result['stage']=='direction'

def test_small_talk_preserves_facts_and_pivot_replaces_direction():
    previous={'version':2,'facts':{'brief':['film'],'direction':['serious']}}
    result=memo.update(previous,[],{'consultation_next':answer('conversation')})
    assert result['facts']==previous['facts']
    changed=memo.update(previous,[{'role':'user','text':'Actually make it a comedy'}],{'memo_direction':answer('0')})
    assert changed['facts']['direction']==['Actually make it a comedy']
    assert previous['facts']['direction']==['serious']

@pytest.mark.asyncio
async def test_agreement_proposes_without_starting_production(monkeypatch):
    monkeypatch.setattr(router.library,'catalog',lambda:[])
    monkeypatch.setattr(reference_url_index,'presentation_rows',lambda:[])
    async def judge(user,state,questions,**kwargs):
        assert 'action' not in questions and 'destination' not in questions
        assert state['consultation_memo']['facts']['brief']==['film']
        return {'available':True,'answers':{'consultation_next':answer('propose'),'memo_direction':answer('0')}}
    monkeypatch.setattr(router.editor_jev,'judge',judge)
    result=await router.decide('u',[{'role':'user','text':'That direction is right'}],include_url_index=True,consultation_memo={'version':2,'facts':{'brief':['film']}})
    assert result['action']=='talk' and not result['needs_backend']
    assert result['consultation_memo']['stage']=='concretize'
    assert result['consultation_memo']['next']=='propose'

def test_bad_legacy_facts_do_not_survive_and_direction_is_not_automatic_progress():
    result=memo.update({'version':1,'facts':{'purpose':['film'],'direction':['film']}},[],{})
    assert result['facts']=={} and result['stage']=='understand'
    result=memo.update({'version':2,'facts':{'brief':['film'],'direction':['closest reference']}},[],{'consultation_next':answer('select')})
    assert result['stage']=='direction'

def test_ready_premise_does_not_override_current_conversation():
    result=memo.update(None,[{'role':'user','text':'farmer story'}],{'memo_brief':answer('0'),'consultation_next':answer('ask'),'request_kind':answer('consultation'),'reference_readiness':answer('ready')})
    assert result['next']=='ask'

def test_final_constraint_proactively_proposes_without_requiring_user_signal():
    previous={'version':2,'facts':{'brief':['film'],'purpose':['personal'],'direction':['warm comedy'],'constraints':['two minutes']}}
    result=memo.update(previous,[{'role':'user','text':'No footage supplied'}],{'consultation_next':answer('propose'),'request_kind':answer('consultation'),'memo_constraints':answer('0'),'memo_direction':answer('unknown')})
    assert result['next']=='propose'
    assert result['facts']['direction']==['warm comedy']
    result=memo.update(result,[{'role':'user','text':'show three references'}],{'consultation_next':answer('compare'),'request_kind':answer('references')})
    assert result['next']=='compare'

@pytest.mark.parametrize('facts', [{}, {'brief':['film'],'purpose':['YouTube'],
    'constraints':['two minutes'],'direction':['comedy']}])
def test_full_memo_or_reference_readiness_never_turns_answer_into_search(facts):
    result=memo.update({'version':2,'facts':facts},[{'role':'user','text':'Give me topic ideas in words'}],
        {'consultation_next':answer('conversation'),'request_kind':answer('references'),
         'reference_readiness':answer('ready')})
    assert result['next']=='conversation'
    assert result['pending_request'] is None
