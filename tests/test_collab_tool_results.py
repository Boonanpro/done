import json

import pytest

from app.agent.v2.tools import format_tool_result


@pytest.mark.parametrize('skill,result', [
    ('_collab_thread', {'success': True, 'collab_room_id': 'test-room',
                       'invite_url': 'https://chat.example/collab/join/test', 'message': '作りました'}),
    ('_collab_thread', {'success': True, 'threads': [{'collab_room_id': 'test-room'}], 'message': '一覧です'}),
    ('_compose_message', {'success': True, 'proposal_id': 'test-proposal', 'message': '送信準備ができました'}),
])
def test_tool_result_retains_data_needed_for_the_next_step(skill, result):
    assert json.loads(format_tool_result(result, skill, 'manage').text) == result
