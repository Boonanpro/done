from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from fastapi import HTTPException
from app.api import voicelog_routes as routes
from app.services import voice_live as live, voice_gemini as gemini
from app.services.project_service import ProjectService


@pytest.mark.asyncio
async def test_foreign_room_cannot_issue_gemini_token():
    with patch.object(routes, '_get_user', return_value=SimpleNamespace(user_id='owner')), \
         patch.object(routes.ChatService, 'get_room', new_callable=AsyncMock, return_value=None), \
         patch.object(gemini, 'provision', new_callable=AsyncMock) as issue:
        with pytest.raises(HTTPException) as error:
            await routes.create_live_session(None, routes.LiveSessionRequest(room_id='foreign', provider='gemini'))
        assert error.value.status_code == 403
        issue.assert_not_called()


@pytest.mark.asyncio
async def test_gemini_retains_astra_history_and_cleans_up_on_provision_failure():
    with patch.object(routes, '_get_user', return_value=SimpleNamespace(user_id='owner')), \
         patch.object(routes.settings, 'GOOGLE_GEMINI_API_KEY', 'private'), \
         patch.object(routes.settings, 'OPENAI_API_KEY', ''), \
         patch.object(routes.ChatService, 'get_room', new_callable=AsyncMock, return_value={'id':'r'}), \
         patch.object(routes.ChatService, 'get_messages', new_callable=AsyncMock, return_value=[{'sender_type':'ai','content':'窓側を希望','created_at':'1'}]), \
         patch.object(ProjectService, 'get_project_by_room_id', new_callable=AsyncMock, return_value=None), \
         patch.object(live, 'warm'), \
         patch.object(gemini, 'provision', new_callable=AsyncMock, return_value={'model':gemini.MODEL,'token':'ephemeral'}) as issue:
        response = await routes.create_live_session(None, routes.LiveSessionRequest(room_id='r', provider='gemini', device=True))
        sid = response['session']['id']
        try:
            assert live._sessions[sid]['user_id'] == 'owner'
            assert '窓側' in str(live._sessions[sid]['history'])
            assert '窓側' in str(issue.call_args.args[1])
            assert any(tool['name'] == 'enter_voice_standby' for tool in live._sessions[sid]['tools'])
        finally:
            live.close(sid, 'owner')
        before = set(live._sessions)
        issue.side_effect = RuntimeError('private')
        with pytest.raises(HTTPException) as error:
            await routes.create_live_session(None, routes.LiveSessionRequest(room_id='r', provider='gemini'))
        assert error.value.status_code == 502
        assert 'private' not in error.value.detail
        assert set(live._sessions) == before
