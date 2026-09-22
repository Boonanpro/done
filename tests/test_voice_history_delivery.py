import json
from unittest.mock import AsyncMock

import pytest
from app.services import voice_intake as vi


@pytest.mark.asyncio
@pytest.mark.parametrize('messages',[
    [{'from':'user','text':'住所は以前伝えた場所です','at':'09-20 03:00'},
     {'from':'dan','text':'記録しました','at':'09-20 03:01'}],
    [{'sender_type':'human','content':'住所は以前伝えた場所です','created_at':'2026-09-20T03:00:00Z'},
     {'sender_type':'ai','content':'記録しました','created_at':'2026-09-20T03:01:00Z'}],
])
async def test_real_client_history_contract_survives_tool_roundtrip(messages):
    agent=vi.VoiceIntake('owner','room')
    call=agent.call('read_room_history',{'limit':30})['output'][0]
    response=await agent.respond([{'type':'function_call_output','call_id':call['call_id'],
        'output':json.dumps({'messages':messages,'next_before':'older'})}],[],'')
    result=json.loads(response['output'][0]['content'][0]['text'])
    assert [m['role'] for m in result['messages']]==['user','assistant']
    assert [m['text'] for m in result['messages']]==['住所は以前伝えた場所です','記録しました']
    assert result['messages'][0]['at']
    assert result['next_before']=='older'
    agent.close()


@pytest.mark.asyncio
async def test_recall_can_reach_memory_worker_instead_of_repeating_recent_page(monkeypatch):
    monkeypatch.setattr(vi,'list_owned',lambda *_:[])
    agent=vi.VoiceIntake('owner','room')
    agent.judge.choose=AsyncMock(return_value={'available':True,'answers':{
        'route':{'choice':'history','confidence':1,'probabilities':{'history':1}}}})
    dialogue=[{'role':'assistant','text':'目印はありますか？'},
              {'role':'user','text':'自宅の場所は前に教えたよね？'}]
    response=await agent.respond([{'content':json.dumps({'dialogue':dialogue})}],[],'')
    call=response['output'][0]
    assert call['name']=='delegate_to_dan'
    task=json.loads(call['arguments'])['task']
    assert dialogue[-1]['text'] in task
    assert dialogue[0]['text'] in task
    agent.close()


def test_history_does_not_drop_older_half_or_truncate_relevant_fact():
    messages=[{'from':'user','text':'長い話。'*200+'最後に答えがあります'} for _ in range(30)]
    result=vi.spoken_result({'messages':messages})
    assert len(result['messages'])==30
    assert all(m['text'].endswith('最後に答えがあります') for m in result['messages'])
