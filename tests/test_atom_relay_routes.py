import json
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import pytest
from fastapi import HTTPException
from app.api import atom_relay_routes as routes

@pytest.mark.asyncio
async def test_pairing_secret_requires_authenticated_room_owner(tmp_path):
    config=tmp_path/'.tmp';config.mkdir()
    (config/'atom-voice-room.json').write_text(json.dumps({'room_id':'device-room'}))
    (config/'atom-wifi-pairing.json').write_text(json.dumps({'ip':'192.168.1.2','key':'secret'}))
    service=SimpleNamespace(get_room=AsyncMock(return_value=None))
    with patch.object(routes,'ROOT',tmp_path),patch.object(routes,'decode_access_token',return_value=SimpleNamespace(user_id='owner')),patch.object(routes,'ChatService',return_value=service):
        with pytest.raises(HTTPException) as error:await routes.paired_device('Bearer valid')
        assert error.value.status_code==403
        service.get_room.assert_awaited_once_with('device-room','owner')
        service.get_room.return_value={'id':'device-room'}
        assert (await routes.paired_device('Bearer valid'))['key']=='secret'

@pytest.mark.asyncio
async def test_invalid_token_never_reads_pairing_files():
    with patch.object(routes,'decode_access_token',return_value=None):
        with pytest.raises(HTTPException) as error:await routes.paired_device('Bearer expired')
        assert error.value.status_code==401

@pytest.mark.asyncio
@pytest.mark.parametrize('status_code', [200,409,503])
async def test_direct_config_waits_for_bridge_release_and_propagates_busy(status_code):
    client=AsyncMock()
    client.__aenter__.return_value=client
    client.post.return_value=SimpleNamespace(status_code=status_code)
    request=SimpleNamespace(headers={'authorization':'Bearer test'})
    pairing={'ip':'192.168.1.2','key':'test-pairing-key'}
    with patch.object(routes,'paired_device',AsyncMock(return_value=pairing)),patch.object(routes.httpx,'AsyncClient',return_value=client):
        if status_code==200:
            result=await routes.direct_config(request)
            assert result['audioOwner']=='phone' and result['host']==pairing['ip']
        else:
            with pytest.raises(HTTPException) as error:await routes.direct_config(request)
            assert error.value.status_code==status_code
        client.post.assert_awaited_once_with('http://127.0.0.1:48801/control',json={
            'key':'test-pairing-key','action':'audio_owner','mode':'phone'})

@pytest.mark.asyncio
async def test_direct_config_never_claims_device_without_room_authorization():
    with patch.object(routes,'paired_device',AsyncMock(side_effect=HTTPException(403))),patch.object(routes.httpx,'AsyncClient') as client:
        with pytest.raises(HTTPException):await routes.direct_config(SimpleNamespace(headers={}))
        client.assert_not_called()
