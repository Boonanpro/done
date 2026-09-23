import json,os
import pytest
from fastapi import HTTPException
from app.core.api import sandbox_routes
from app.core.api.sandbox_routes import _recent_voice_sessions

def test_active_closed_and_expired_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_routes,'_live_phone_calls',lambda *a,**k:[])   # phone calls come from the real sideband log
    p=tmp_path/'room'/'assistant'/'events'/'session.jsonl';p.parent.mkdir(parents=True)
    p.write_text(json.dumps({'type':'live_usage'})+'\n')
    os.utime(p,(1000,1000))
    assert _recent_voice_sessions(tmp_path,1040)==['room']
    assert _recent_voice_sessions(tmp_path,1091)==[]
    p.write_text(json.dumps({'type':'live_usage'})+'\n'+json.dumps({'type':'live_session_closed'})+'\n')
    os.utime(p,(1000,1000))
    assert _recent_voice_sessions(tmp_path,1040)==[]

@pytest.mark.asyncio
async def test_restart_cannot_force_through_an_active_voice(monkeypatch):
    monkeypatch.setattr(sandbox_routes,'_recent_voice_sessions',lambda:['room'])
    class Manager:
        def restart(self,**kwargs):raise AssertionError('must not interrupt voice')
    monkeypatch.setattr(sandbox_routes,'_manager',Manager())
    for force in (False,True):
        with pytest.raises(HTTPException) as error:
            await sandbox_routes.restart_sandbox(sandbox_routes.RestartRequest(force=force))
        assert error.value.status_code==409
