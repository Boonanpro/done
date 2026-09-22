import copy
import json
import pytest
from app.services import editor_direction_library as lib
from app.services import editor_presentation as presentation, editor_jev
from tests.test_editor_project import room


def plan():
    return {'title': '試作', 'beats': [
        {'pattern': 'reveal', 'duration': 4, 'headline': '相談を、もっと簡単に。'},
        {'pattern': 'path', 'duration': 4, 'headline': '進み方', 'labels': ['選ぶ', '送る', '話す']}]}


def test_revision_preserves_other_scene_and_timeline(room):
    path, seq = room
    first = lib.preview('room', 'c', plan())['presentation']['items'][0]
    second = presentation.revise('room', 'c', first['id'], [{'path': '/scene/params/beats/1/headline', 'value': '一歩ずつ'}])['presentation']['items'][0]
    assert second['scene']['code'] == first['scene']['code']
    assert second['scene']['params']['beats'][0] == first['scene']['params']['beats'][0]
    assert first['scene']['params']['beats'][1]['headline'] == '進み方'
    assert second['scene']['params']['beats'][1]['headline'] == '一歩ずつ'
    content = json.loads((path/'contents.json').read_text(encoding='utf-8'))[0]
    assert content['timeline']['sequence'] == seq
    assert len(content['proposal_history']) == 2


@pytest.mark.parametrize('change', [
    {'pattern': 'invented'}, {'duration': float('nan')}, {'headline': ''},
    {'labels': ['a'*19]}, {'pace': 0}, {'pattern': 'compare', 'labels': ['one']},
])
def test_invalid_plan_rejected_before_persisting(room, change):
    source=plan();source['beats'][0].update(change)
    with pytest.raises(ValueError):lib.preview('room', 'c', source)
    assert 'proposal_history' not in json.loads((room[0]/'contents.json').read_text(encoding='utf-8'))[0]


@pytest.mark.asyncio
async def test_ranking_is_advice_and_failure_keeps_available_primitives(monkeypatch):
    async def unavailable(*a, **kw):return {'available': False, 'elapsed_ms': 20}
    monkeypatch.setattr(editor_jev, 'judge', unavailable)
    result=await lib.search('u','依頼',[])
    assert not result['ranking_available']
    assert len(result['patterns']) == 6


def test_tools_reach_conversation_model():
    from app.api.editor_assistant_routes import EDITOR_TOOLS
    from app.services.editor_reasoning import tools_for_conversation
    names={t['name'] for t in tools_for_conversation(EDITOR_TOOLS)}
    assert {'find_direction_patterns','preview_direction_plan'} <= names
