import json
from unittest.mock import AsyncMock
import pytest
from app.services import voice_intake as vi

def input_for(text):return [{'type':'message','role':'user','content':[{'type':'input_text','text':json.dumps({'utterance_final':False,'dialogue':[{'role':'user','text':text}]})}]}]
def answer(route,conf=1,target=None):
    rows={'route':{'choice':route,'confidence':conf,'probabilities':{route:conf}}}
    if target:rows['target']={'choice':target,'confidence':1,'probabilities':{target:1}}
    return {'available':True,'answers':rows}

def both(route_answer,field_answer=None,complete_answer=None):
    """Route and saved-fact judgements run concurrently: answer by the question asked, not by call order."""
    async def choose(state,questions):
        if 'field' in questions:return field_answer or {'available':False}
        if 'complete' in questions:return complete_answer or {'available':False}
        return route_answer
    return AsyncMock(side_effect=choose)

@pytest.mark.asyncio
async def test_uncertain_followup_reaches_single_worker_without_cancel(monkeypatch):
    job={'id':'job','state':'running','task':'予約の確認'}
    monkeypatch.setattr(vi,'list_owned',lambda *_:[job])
    a=vi.VoiceIntake('user','room')
    decision=answer('cancel',.7,'job')
    decision['answers']['target'].update(confidence=.59,probabilities={'job':.8,'none':.2})
    a.judge.choose=AsyncMock(return_value=decision)
    text='確定しないで。先に乗車日を教えて'
    result=await a.respond(input_for(text),[],'')
    call=result['output'][0]
    assert call['name']=='control_dan_task'
    assert json.loads(call['arguments'])=={'job_id':'job','operation':'update','task':text}

@pytest.fixture
def agent(monkeypatch):
    from app.services import voice_search_reader
    from types import SimpleNamespace
    class Reader:
        def __init__(self):
            self.agent=SimpleNamespace(closed=False)
            self.read=AsyncMock(side_effect=lambda dialogue,data,on_text=None:
                {'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(data)}]}]})
        def close(self):self.agent.closed=True
    monkeypatch.setattr(voice_search_reader,'SearchReader',Reader)
    monkeypatch.setattr(vi,'list_owned',lambda *_:[])
    from unittest.mock import MagicMock
    empty=MagicMock();empty.list_masked_sync=lambda user:[]
    monkeypatch.setattr('app.services.personal_info_service.PersonalInfoService',lambda:empty)
    a=vi.VoiceIntake('user','room');a.judge.choose=AsyncMock(return_value=answer('work'))
    return a

@pytest.mark.asyncio
async def test_original_request_goes_to_worker_without_coordinator(agent):
    text='予約内容を確認して。まだ購入しないで'
    response=await agent.respond(input_for(text),[],'')
    call=response['output'][0]
    assert call['name']=='delegate_to_dan'
    assert text in json.loads(call['arguments'])['task']
    agent.judge.choose.assert_awaited_once()
    result=await agent.respond([{'type':'function_call_output','call_id':call['call_id'],'output':'{"accepted":true}'}],[],'')
    assert result['output'][0]['type']=='message'
    agent.judge.choose.assert_awaited_once()
    with pytest.raises(ValueError):
        await agent.respond([{'type':'function_call_output','call_id':call['call_id'],'output':'{}'}],[],'')

@pytest.mark.asyncio
async def test_uncertainty_still_goes_to_single_worker(agent):
    agent.judge.choose.return_value=answer('work',.5)
    result=await agent.respond(input_for('あの予約を取り消して'),[],'')
    assert result['output'][0]['name']=='delegate_to_dan'

@pytest.mark.asyncio
async def test_search_uses_original_words(agent):
    agent.judge.choose.return_value=answer('search')
    result=await agent.respond(input_for('日本交通の当日ネット予約は可能？'),[],'')
    call=result['output'][0]
    assert call['name']=='web_search'
    assert json.loads(call['arguments'])=={'query':'日本交通の当日ネット予約は可能？'}

@pytest.mark.asyncio
async def test_no_active_job_cannot_be_classified_as_job_cancellation(agent):
    await agent.respond(input_for('その予約をキャンセルして'),[],'')
    options=agent.judge.choose.call_args.args[1]['route']['criteria']
    assert not {'pause','cancel','confirm','update'} & options.keys()
    assert 'work' in options

@pytest.mark.asyncio
async def test_unavailable_classifier_does_not_invent_a_work_change(agent,monkeypatch):
    monkeypatch.setattr(vi,'list_owned',lambda *_:[{'id':'j','task':'予約確認','state':'running'}])
    agent.judge.choose.return_value={'available':False}
    result=await agent.respond(input_for('買わないで、値段だけ教えて'),[],'')
    call=result['output'][0]
    assert call['name']=='control_dan_task'
    assert json.loads(call['arguments'])=={'job_id':'j','operation':'pause','task':'買わないで、値段だけ教えて'}

@pytest.mark.asyncio
async def test_production_room_registers_intake_without_starting_astra():
    from app.services import voice_live
    voice_live.register('intake-test','user','',[],room_id='room')
    try:
        assert isinstance(voice_live._sessions['intake-test']['agent'],vi.VoiceIntake)
        voice_live.warm('intake-test')
    finally:voice_live.close('intake-test','user')

@pytest.mark.asyncio
async def test_approval_bound_to_proposal_and_complete_utterance(agent,monkeypatch):
    from app.services.voice_approval import valid
    job={'id':'j','task':'予約取消','state':'awaiting_confirmation','confirmation':{'id':'p','summary':'手数料320円で取消してよい？'}}
    monkeypatch.setattr(vi,'list_owned',lambda *_:[job])
    result=answer('work',.5,'j')
    result['answers']['approval']={'choice':'approved','confidence':1,'probabilities':{'approved':1}}
    agent.judge.choose.return_value=result
    inp=input_for('うん、払い戻してください')
    assert (await agent.respond(inp,[],''))['awaiting_final_input']
    data=json.loads(inp[0]['content'][0]['text']);data['utterance_final']=True
    inp[0]['content'][0]['text']=json.dumps(data)
    call=(await agent.respond(inp,[],''))['output'][0];args=json.loads(call['arguments'])
    assert args['operation']=='confirm'
    assert valid(args['voice_approval'],'user','room','j','p',args['task'])
    assert not valid(args['voice_approval'],'user','room','j','different',args['task'])
    assert not valid(args['voice_approval'],'user','room','j','p','different words')

@pytest.mark.asyncio
async def test_status_and_smalltalk_do_not_modify_existing_job(agent,monkeypatch):
    monkeypatch.setattr(vi,'list_owned',lambda *_:[{'id':'j','task':'予約取消','state':'running'}])
    agent.judge.choose.return_value=answer('status',.5)
    seen=(await agent.respond(input_for('今何を待ってる？'),[],''))['data']
    # answered from the job files at once, not by a tool call that carried the whole job list through the phone
    assert seen['work_status'][0]['依頼']=='予約取消' and seen['work_status'][0]['状態']=='作業中'
    agent.judge.choose.return_value=answer('other',.5)
    result=await agent.respond(input_for('今日は早起きしたよ'),[],'')
    # one factual line: no instructions to the speech model, no conversation sent back in pieces
    assert result['output'][0]['content'][0]['text']=='調べる内容のない会話でした。'

@pytest.mark.asyncio
async def test_search_preserves_sources_without_classifier_censorship(agent):
    agent.dialogue=[{'role':'user','text':'A社の当日予約は可能？'}]
    call=agent.call('web_search',{'query':'A社の当日予約は可能？'})['output'][0]
    agent.judge.choose.return_value={'answers':{'1':{'choice':'yes','confidence':1,'probabilities':{'yes':1}},'passage_1':{'choice':'0'}}}
    sources=[{'title':'B社','snippet':'予約可能','url':'https://example.invalid/b'},
             {'title':'A社','snippet':'当日は電話で予約','url':'https://example.invalid/a'}]
    result=await agent.respond([{'type':'function_call_output','call_id':call['call_id'],
        'output':json.dumps({'results':sources})}],[],'')
    data=(result.get('data') or json.loads(result['output'][0]['content'][0]['text']))
    assert data['results']==sources
    agent.search_reader.read.assert_awaited_once()
    assert agent.search_reader.read.call_args.args[0]==agent.dialogue
    agent.judge.choose.assert_not_awaited()
    assert not agent.pending


@pytest.mark.asyncio
async def test_uncertain_search_is_not_an_automatic_second_investigation(agent):
    agent.dialogue=[{'role':'user','text':'この便は当日予約できる？'}]
    call=agent.call('web_search',{'query':'この便は当日予約できる？'})['output'][0]
    agent.judge.choose.return_value={'answers':{'0':{'choice':'no','confidence':1,'probabilities':{'no':1}}}}
    result=await agent.respond([{'type':'function_call_output','call_id':call['call_id'],
        'output':json.dumps({'results':[{'title':'別の路線','snippet':'予約できます'}]})}],[],'')
    message=result['output'][0]
    assert message['type']=='message'
    data=json.loads(message['content'][0]['text'])
    assert len(data['results'])==1
    assert data['results'][0]['title']=='別の路線'
    assert not agent.pending

@pytest.mark.asyncio
async def test_search_followup_carries_selected_referent(agent):
    agent.judge.choose.return_value=answer('search')
    agent.judge.choose.return_value['answers']['search_context']={'choice':'1'}
    dialogue=[{'role':'user','text':'京都で夜まで開いてる書店ある？'},
              {'role':'assistant','text':'丸善京都本店は河原町通沿いにあります。'},
              {'role':'user','text':'そこまで京都駅からバスなら？'}]
    inp=[{'content':json.dumps({'dialogue':dialogue})}]
    call=(await agent.respond(inp,[],''))['output'][0]
    query=json.loads(call['arguments'])['query']
    assert '丸善京都本店' in query and dialogue[-1]['text'] in query

@pytest.mark.asyncio
async def test_search_reader_reused_and_closed_with_voice(agent):
    agent.judge.choose.return_value=answer('search')
    await agent.respond(input_for('今開いている店ある？'),[],'')
    reader=agent.search_reader
    await agent.respond(input_for('その店の住所は？'),[],'')
    assert agent.search_reader is reader
    agent.close()
    assert reader.agent.closed

@pytest.mark.asyncio
async def test_search_failure_can_be_investigated_by_reader(agent):
    agent.dialogue=[{'role':'user','text':'東京国立博物館は日曜何時まで？'}]
    call=agent.call('web_search',{'query':'東京国立博物館 日曜 開館時間'})['output'][0]
    failure={'error':'Search provider timed out'}
    await agent.respond([{'type':'function_call_output','call_id':call['call_id'],
        'output':json.dumps(failure)}],[],'')
    assert agent.search_reader.read.call_args.args == (agent.dialogue,failure,None)
    agent.judge.choose.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('saved,expected',[
    ('🎙 うん、払い戻して',True),('🎙 うん、払い戻して。でもまだ実行しないで',False)])
async def test_legacy_approval_requires_whole_saved_reply(monkeypatch,saved,expected):
    from app.services.chat_service import ChatService
    monkeypatch.setattr(ChatService,'get_messages',AsyncMock(return_value=[{'sender_type':'human',
        'content':saved,'created_at':'2026-09-18T00:00:02+09:00'}]))
    assert await vi.saved_final_reply('user','room','うん、払い戻して',{'created_at':'2026-09-18T00:00:01+09:00'}) is expected

@pytest.mark.asyncio
async def test_legacy_reply_waits_for_transcript_after_previous_question(monkeypatch):
    from app.services.chat_service import ChatService
    messages=AsyncMock(side_effect=[
        [{'sender_type':'human','content':'今どうなってる？','created_at':'2026-09-18T00:00:02+09:00'}],
        [{'sender_type':'human','content':'🎙 うん、払い戻して','created_at':'2026-09-18T00:00:05+09:00'}]])
    monkeypatch.setattr(ChatService,'get_messages',messages)
    assert await vi.saved_final_reply('user','room','うん、払い戻して',{'created_at':'2026-09-18T00:00:01+09:00'})
    assert messages.await_count==2


# ---- saved-fact fast path: 「俺の住所どこだっけ」 is answered from saved information, not by starting a job
SAVED=[{'field_key':'address_jp','category':'address','label':'住所(日本語)'},
       {'field_key':'phone_local','category':'contact','label':'電話(国内)'},
       {'field_key':'card_number','category':'payment','label':'アメックス カード番号'},
       {'field_key':'rakuten_bank_pin','category':'payment','label':'楽天銀行 口座暗証番号'},
       {'field_key':'x_2fa_backup','category':'identity','label':'X 2段階認証バックアップコード'}]

def saved_service(monkeypatch,value='福岡県北九州市（テスト用の住所）'):
    from unittest.mock import MagicMock
    service=MagicMock();service.list_masked_sync=lambda user:SAVED
    service.get=AsyncMock(return_value={'label':'住所(日本語)','value':value})
    monkeypatch.setattr('app.services.personal_info_service.PersonalInfoService',lambda:service)
    return service

def field(choice,conf=.99,**others):
    probabilities={choice:conf,**others}
    if 'none' not in probabilities:probabilities['none']=round(1-sum(probabilities.values()),4)
    return {'available':True,'answers':{'field':{'choice':choice,'confidence':conf,'probabilities':probabilities}}}

@pytest.mark.asyncio
async def test_saved_fact_is_answered_without_a_job(agent,monkeypatch):
    service=saved_service(monkeypatch)
    agent.judge.choose=both(answer('history'),field('address_jp'))
    result=await agent.respond(input_for('俺の住所どこだっけ'),[],'')
    spoken=(result.get('data') or json.loads(result['output'][0]['content'][0]['text']))
    assert result['output'][0]['type']=='message' and spoken['saved_information'][0]['value'].startswith('福岡県')
    service.get.assert_awaited_once_with('user','address_jp')

@pytest.mark.asyncio
async def test_doubt_or_no_single_item_still_goes_to_the_worker(agent,monkeypatch):
    service=saved_service(monkeypatch)
    # the real 'バスの会社' case: a company-name item got .29, 'not a saved fact' .70
    for second in (field('none'),field('none',.70,address_jp=.29),field('address_jp',.48,none=.52),{'available':False,'reason':'unavailable'}):
        agent.judge.choose=both(answer('history'),second)
        result=await agent.respond(input_for('さっき調べたバスの会社はどこだった'),[],'')
        assert result['output'][0]['name']=='delegate_to_dan'
    service.get.assert_not_awaited()

@pytest.mark.asyncio
async def test_other_routes_do_not_pay_for_the_extra_question(agent,monkeypatch):
    saved_service(monkeypatch)
    agent.judge.choose=AsyncMock(return_value=answer('work'))
    await agent.respond(input_for('明日の新幹線を予約して'),[],'')
    agent.judge.choose.assert_awaited_once()

@pytest.mark.asyncio
async def test_the_same_fact_saved_under_two_keys_is_still_answered(agent,monkeypatch):
    service=saved_service(monkeypatch)
    SAVED.append({'field_key':'address_home','category':'address','label':'自宅住所'})
    try:
        # the real '俺の住所どこだっけ' distribution: .44 / .20 across two address items, .36 'not a saved fact'
        agent.judge.choose=both(answer('history'),field('address_jp',.44,address_home=.20,none=.36))
        result=await agent.respond(input_for('俺の住所どこだっけ'),[],'')
        assert result['output'][0]['type']=='message' and service.get.await_count==2
    finally:
        SAVED.pop()

@pytest.mark.asyncio
async def test_tell_me_my_x_routed_as_other_is_answered_instead_of_could_not_identify(agent,monkeypatch):
    service=saved_service(monkeypatch)
    agent.judge.choose=both(answer('other',.85),field('phone_local',.58,none=.41))
    result=await agent.respond(input_for('俺の電話番号教えて'),[],'')
    assert result['data']['saved_information'] and result['output'][0]['content'][0]['text'].startswith('本人が保存している情報です。')
    agent.judge.choose=both(answer('other',.9),field('none'))
    unclear=await agent.respond(input_for('あれどうなった'),[],'')
    assert unclear['output'][0]['content'][0]['text']=='調べる内容のない会話でした。'

@pytest.mark.asyncio
async def test_every_saved_item_may_be_answered_by_voice(agent,monkeypatch):
    # Owner's decision: no category is withheld from speech; they adjust per item later if needed.
    service=saved_service(monkeypatch,value='1234')
    agent.judge.choose=both(answer('history'),field('rakuten_bank_pin',.9,none=.1))
    result=await agent.respond(input_for('楽天銀行の暗証番号なんだっけ'),[],'')
    spoken=(result.get('data') or json.loads(result['output'][0]['content'][0]['text']))
    assert spoken['saved_information'][0]['value']=='1234'
    service.get.assert_awaited_once_with('user','rakuten_bank_pin')

@pytest.mark.asyncio
async def test_follow_up_routed_as_conversation_still_looks_up_the_saved_fact(agent,monkeypatch):
    service=saved_service(monkeypatch)
    agent.judge.choose=both(answer('conversation'),field('address_jp',.8,none=.2))
    result=await agent.respond(input_for('住所はその後に続く'),[],'')
    spoken=(result.get('data') or json.loads(result['output'][0]['content'][0]['text']))
    assert spoken['saved_information'][0]['value'].startswith('福岡県') and '省略せず' in spoken['note']
    # ordinary small talk is unchanged
    agent.judge.choose=both(answer('conversation'),field('none'))
    chat=await agent.respond(input_for('なるほどね'),[],'')
    assert chat['output'][0]['content'][0]['text']=='調べる内容のない会話でした。'

@pytest.mark.asyncio
async def test_a_fact_about_the_owner_that_is_not_saved_leads_to_an_offer_to_save_it(agent,monkeypatch):
    saved_service(monkeypatch)
    missing=field('none',.9)
    missing['answers']['about_self']={'choice':'self_fact','confidence':.95,'probabilities':{'self_fact':.95,'other':.05}}
    agent.judge.choose=both(answer('other',.8),missing)
    result=await agent.respond(input_for('俺の血液型なんだっけ'),[],'')
    spoken=(result.get('data') or json.loads(result['output'][0]['content'][0]['text']))
    assert spoken.get('not_saved') is True and '保存できる' in spoken['note']


def with_web(decision,p):
    decision['answers']['web']={'choice':'needed' if p>=.5 else 'not_needed','confidence':1,'probabilities':{'needed':p,'not_needed':round(1-p,4)}}
    return decision

def outside(p):return {'available':True,'answers':{'complete':{'choice':'needs_outside' if p>=.5 else 'complete','confidence':1,'probabilities':{'needs_outside':p,'complete':round(1-p,4)}}}}

def with_act(decision,p):
    decision['answers']['act']={'choice':'do' if p>=.5 else 'no','confidence':1,'probabilities':{'do':p,'no':round(1-p,4)}}
    return decision

def ingredient(key,p=.9):
    return {'available':True,'answers':{'field':{'choice':'none','confidence':1,'probabilities':{'none':1}},
        'ingredient':{'choice':key,'confidence':p,'probabilities':{key:p,'none':round(1-p,4)}}}}

@pytest.mark.asyncio
async def test_question_needing_a_saved_fact_and_the_web_gets_both(agent,monkeypatch):
    # The owner's phone test: 「JR尼崎駅と郵便番号同じ?」 answered the saved postcode alone, then "cannot tell from what is registered".
    service=saved_service(monkeypatch,value='SECRET-VALUE')
    agent.judge.choose=both(with_web(answer('conversation'),.9),field('address_jp',.9,none=.1),outside(.9))
    call=(await agent.respond(input_for('JR尼崎駅と郵便番号同じ?'),[],''))['output'][0]
    assert call['name']=='web_search' and 'SECRET-VALUE' not in call['arguments']
    assert 'SECRET-VALUE' not in json.dumps(agent.pending,ensure_ascii=False)   # the pending call is persisted
    result=await agent.respond([{'type':'function_call_output','call_id':call['call_id'],'output':json.dumps({'results':['x']})}],[],'')
    seen=(result.get('data') or json.loads(result['output'][0]['content'][0]['text']))
    assert seen['saved_information'][0]['value']=='SECRET-VALUE' and seen['results']==['x']

@pytest.mark.asyncio
async def test_saved_fact_alone_is_not_slowed_by_a_search(agent,monkeypatch):
    saved_service(monkeypatch)
    # 「免許の有効期限っていつまで」 looks like a web question on its own; naming the matched item settles it
    agent.judge.choose=both(with_web(answer('history'),.8),field('address_jp',.9,none=.1),outside(.1))
    result=await agent.respond(input_for('俺の住所教えて'),[],'')
    spoken=(result.get('data') or json.loads(result['output'][0]['content'][0]['text']))
    assert spoken['saved_information'] and 'next' not in spoken and 'role' not in spoken and 'keys' not in spoken

@pytest.mark.asyncio
async def test_asking_again_climbs_to_search_then_to_dan(agent,monkeypatch):
    saved_service(monkeypatch)
    agent.judge.choose=both(with_web(answer('conversation'),.2),field('address_jp',.9,none=.1))
    first=await agent.respond(input_for('それって駅から近い?'),[],'')
    assert first['output'][0]['type']=='message'
    second=(await agent.respond(input_for('それって駅から近い?'),[],''))['output'][0]
    assert second['name']=='web_search'
    third=(await agent.respond(input_for('それって駅から近い?'),[],''))['output'][0]
    assert third['name']=='delegate_to_dan'

@pytest.mark.asyncio
async def test_lost_judgement_is_retried_and_never_becomes_a_job(agent):
    agent.judge.choose=AsyncMock(return_value={'available':False})
    result=await agent.respond(input_for('ああ、なるほどね'),[],'')
    assert result['output'][0]['type']=='message'
    assert (result.get('data') or json.loads(result['output'][0]['content'][0]['text']))['status']=='intent_not_judged'
    assert sum(1 for c in agent.judge.choose.await_args_list if 'route' in c.args[1])==2

@pytest.mark.asyncio
async def test_speech_models_own_request_reaches_the_judgement(agent):
    agent.judge.choose=both(with_web(answer('search'),.9))
    items=[{'type':'message','role':'user','content':[{'type':'input_text','text':json.dumps({'utterance_final':True,
        'dialogue':[{'role':'user','text':'どういうこと?'}],'request':'JR尼崎駅の郵便番号をウェブで調べる'})}]}]
    call=(await agent.respond(items,[],''))['output'][0]
    assert call['name']=='web_search'
    state=next(c.args[0] for c in agent.judge.choose.await_args_list if 'route' in c.args[1])
    assert state['speech_model_request']=='JR尼崎駅の郵便番号をウェブで調べる'

@pytest.mark.asyncio
async def test_saved_item_needed_as_an_ingredient_travels_with_the_search(agent,monkeypatch):
    saved_service(monkeypatch,value='SECRET-VALUE')
    agent.judge.choose=both(with_web(answer('search'),.95),ingredient('address_jp'))
    call=(await agent.respond(input_for('うちから一番近いコンビニってどこ'),[],''))['output'][0]
    assert call['name']=='web_search' and agent.pending[call['call_id']]['saved']==['address_jp'] and 'SECRET-VALUE' not in call['arguments']
    agent.judge.choose=both(with_web(answer('other'),.1),ingredient('address_jp'))
    talk=await agent.respond(input_for('うちは今日静かだよ'),[],'')
    assert 'saved_information' not in talk['output'][0]['content'][0]['text']   # an ingredient alone answers nothing

@pytest.mark.asyncio
async def test_request_to_act_is_work_even_when_routed_as_small_talk(agent):
    agent.judge.choose=both(with_act(with_web(answer('other',.7),.0),.95))
    call=(await agent.respond(input_for('俺の血液型O型だから保存しといて'),[],''))['output'][0]
    assert call['name']=='delegate_to_dan'
    agent.judge.choose=both(with_act(with_web(answer('other',.7),.0),.1))
    assert (await agent.respond(input_for('今日は早起きしたよ'),[],''))['output'][0]['type']=='message'


def with_where(decision,place,p=.9):
    decision['answers']['where']={'choice':place,'confidence':p,'probabilities':{place:p}}
    return decision

@pytest.mark.asyncio
async def test_question_about_the_past_is_answered_from_the_records_not_by_a_job(agent,monkeypatch):
    # The owner's phone test: 「この前の新幹線、結局キャンセルできたんだっけ」 became a job list and "tell me again".
    from app.services import voice_past
    found={'keywords':['新幹線'],'records':[{'at':'2026-09-17T22:00','who':'user','text':'キャンセルして'}],'jobs':[],'elapsed_ms':5}
    monkeypatch.setattr(voice_past,'gather',AsyncMock(return_value=found))
    agent.judge.choose=both(with_where(answer('other',.6),'past'))
    result=await agent.respond(input_for('この前の新幹線って結局キャンセルできたんだっけ'),[],'')
    seen=(result.get('data') or json.loads(result['output'][0]['content'][0]['text']))
    assert seen['past_records']==found['records'] and result['output'][0]['type']=='message'
    again=(await agent.respond(input_for('この前の新幹線って結局キャンセルできたんだっけ'),[],''))['output'][0]
    assert again['name']=='delegate_to_dan'   # the records were not enough: now Dan itself looks

@pytest.mark.asyncio
async def test_past_question_without_any_record_goes_to_dan_with_the_voice_rules(agent,monkeypatch):
    from app.services import voice_past
    monkeypatch.setattr(voice_past,'gather',AsyncMock(return_value={'keywords':[],'records':[],'jobs':[],'elapsed_ms':5}))
    agent.judge.choose=both(answer('history'))
    call=(await agent.respond(input_for('あの件どうなった'),[],''))['output'][0]
    task=json.loads(call['arguments'])['task']
    assert call['name']=='delegate_to_dan' and '音声通話からの依頼' in task and '承認を求めずに進める' in task

@pytest.mark.asyncio
async def test_progress_of_work_is_not_an_available_meaning_when_nothing_is_running(agent):
    agent.judge.choose=both(answer('other'))
    await agent.respond(input_for('新幹線どうなった'),[],'')
    questions=next(c.args[1] for c in agent.judge.choose.await_args_list if 'route' in c.args[1])
    assert 'status' not in questions['route']['criteria'] and 'running' not in questions['where']['criteria'] and 'past' in questions['where']['criteria']


@pytest.mark.asyncio
async def test_question_without_a_place_uses_where_the_owner_is(agent,monkeypatch):
    # 「今日天気悪い?」 made the reader ask "which town are you in?".
    saved_service(monkeypatch)
    from app.services import user_location
    monkeypatch.setattr(user_location,'place_for_speech',lambda user:{'current_place':'東京都千代田区丸の内一丁目','minutes_ago':3,'note':''})
    here={'available':True,'answers':{'field':{'choice':'none','confidence':1,'probabilities':{'none':1}},
        'ingredient':{'choice':vi.HERE,'confidence':.9,'probabilities':{vi.HERE:.9,'none':.1}}}}
    agent.judge.choose=both(with_web(answer('search'),.95),here)
    call=(await agent.respond(input_for('今日天気悪い?'),[],''))['output'][0]
    assert call['name']=='web_search' and json.loads(call['arguments'])['query'].startswith('東京都千代田区丸の内一丁目 ')
    result=await agent.respond([{'type':'function_call_output','call_id':call['call_id'],'output':json.dumps({'results':[]})}],[],'')
    assert (result.get('data') or json.loads(result['output'][0]['content'][0]['text']))['place']['current_place']=='東京都千代田区丸の内一丁目'


@pytest.mark.asyncio
async def test_follow_up_work_carries_the_job_that_just_ended(agent,monkeypatch):
    from datetime import datetime,timezone
    ended={'id':'j1','state':'completed','task':'新幹線がキャンセルできたか確認して','result':'完了の記録は無し。EXサイトは未確認。',
        'updated_at':datetime.now(timezone.utc).isoformat(),'events':[{'kind':'tool','text':'lookup'},{'kind':'tool','text':'browser:open_target'}]}
    monkeypatch.setattr(vi,'list_owned',lambda *_:[ended])
    agent.judge.choose=both(answer('work'))
    task=json.loads((await agent.respond(input_for('うん、進めてください'),[],''))['output'][0]['arguments'])['task']
    assert '直前に終わった作業' in task and 'EXサイトは未確認' in task and 'browser:open_target' in task and 'やり直さず' in task
    ended['updated_at']='2026-01-01T00:00:00+00:00'   # an old job is not the context of today's request
    task=json.loads((await agent.respond(input_for('メール送っといて'),[],''))['output'][0]['arguments'])['task']
    assert '直前に終わった作業' not in task


@pytest.mark.asyncio
async def test_told_to_hang_up_it_hangs_up(agent):
    # 「電話切れ」 twice in the owner's calls: judged 'end' under the bar, so the call stayed up.
    agent.judge.choose=both(answer('end',.55))
    assert (await agent.respond(input_for('死ね。電話消せ'),[],''))['output'][0]['name']=='enter_voice_standby'
    agent.judge.choose=AsyncMock(return_value={'available':False})   # even when the judgement is lost
    assert (await agent.respond(input_for('おい、聞こえてんのか、電話切れって言ってんだよ'),[],''))['output'][0]['name']=='enter_voice_standby'
    agent.judge.choose=both(answer('other',.9))
    assert (await agent.respond(input_for('さっき電話切れたのなんで?'),[],''))['output'][0]['type']=='message'   # talking about a hang-up is not an order

@pytest.mark.asyncio
async def test_new_request_while_a_job_runs_is_not_answered_with_that_job(agent,monkeypatch):
    # 「二十四日にカレンダーに予定入ってるよね」 three times while the ticket job ran: each time the ticket job's state came back.
    monkeypatch.setattr(vi,'list_owned',lambda *_:[{'id':'j','task':'新幹線の払い戻し確認','state':'running','events':[{'kind':'progress','text':'EXサイトにログイン中'}]}])
    decision=with_where(answer('work',.7,'j'),'site',.9)
    decision['answers']['target'].update(confidence=.6,probabilities={'j':.6,'none':.4})
    agent.judge.choose=both(decision)
    call=(await agent.respond(input_for('二十四日にカレンダーに予定入ってるよね'),[],''))['output'][0]
    assert call['name']=='delegate_to_dan'
    agent.judge.choose=both(with_where(answer('other',.6,'j'),'running',.9))
    seen=(await agent.respond(input_for('今ログインしようとしてるの?'),[],''))['data']
    assert seen['work_status'][0]['今やっていること']=='EXサイトにログイン中'

@pytest.mark.asyncio
async def test_saved_item_is_not_read_aloud_when_nobody_asked_for_it(agent,monkeypatch):
    # 「二十四日って言ってんの」 -> an e-Tax number was spoken.
    service=saved_service(monkeypatch,value='SECRET-NUMBER')
    hit=field('address_jp',.9,none=.1)
    hit['answers']['about_self']={'choice':'other','confidence':.9,'probabilities':{'self_fact':.1,'other':.9}}
    agent.judge.choose=both(answer('conversation'),hit)
    result=await agent.respond(input_for('二十四日って言ってんの'),[],'')
    assert 'SECRET-NUMBER' not in json.dumps(result,ensure_ascii=False)


def test_results_reach_the_speech_model_as_plain_words_not_json():
    # The phone app cuts JSON into 480-byte pieces and adds 「確認結果を受信しました…」, which the speech model was heard repeating.
    said=vi.plain({'saved_information':[{'label':'郵便番号','value':'660-0807','say':'ろくろくゼロの、ゼロはちゼロなな'}]})
    assert said=='本人が保存している情報です。郵便番号は、ろくろくゼロの、ゼロはちゼロなな。省略せずに伝えてください。'
    status=vi.plain(vi.work_status([{'task':'新幹線の払い戻しを確認','state':'running','events':[{'kind':'progress','text':'EXサイトにログイン中'},{'kind':'tool','text':'browser:click'}]}]))
    assert 'EXサイトにログイン中' in status and 'browser:click' not in status and '{' not in status
    assert vi.plain({'work_status':[]})=='今は何も作業していません。'


@pytest.mark.asyncio
async def test_question_that_found_nothing_moves_on_by_itself_instead_of_telling_the_speech_model_what_to_do(agent,monkeypatch):
    # 「俺が誰か分かってる?」: the reply was an instruction ("nothing to add; ask again with what you need"). The backend now takes
    # the next step itself: the owner's records.
    from app.services import voice_past
    found={'keywords':['名前'],'records':[{'at':'','who':'dan','text':'みきさん、おはようございます'}],'jobs':[],'elapsed_ms':3}
    monkeypatch.setattr(voice_past,'gather',AsyncMock(return_value=found))
    agent.judge.choose=both(with_where(answer('conversation'),'saved',.7),field('none'))
    result=await agent.respond(input_for('だから名前分かってんのかって聞いてんだよ'),[],'')
    assert json.loads(result['output'][0]['content'][0]['text'])['past_records']==found['records']
    agent.judge.choose=both(with_where(answer('other'),'now',.9),field('none'))
    assert (await agent.respond(input_for('へえ、そうなんだ'),[],''))['output'][0]['content'][0]['text']=='調べる内容のない会話でした。'


def test_job_status_comes_from_what_the_tool_layer_recorded_not_from_the_models_notes():
    # 「今ブラウザ操作してログインしようとしてるの?」: the job's own notes said only "checking the request".
    job={'task':'新幹線の払い戻しをEXサイトで確認','state':'running','events':[{'kind':'progress','text':'依頼内容を確認しています'}],
         'current_tool':{'name':'browser','action':'fill_credential'},
         'last_observation':{'text':'URL: https://shinkansen2.jr-central.co.jp/RSV_P/smart_index.htm'+chr(10)+'タイトル: スマートEX ログイン'+chr(10)+'本文…'}}
    said=vi.plain(vi.work_status([job]))
    assert '「スマートEX ログイン」（shinkansen2.jr-central.co.jp）' in said and '今ログイン情報を入力している' in said
    assert '依頼内容を確認しています' not in said and 'fill_credential' not in said
