import asyncio
import pytest
from app.services import browser_operation_lock as L

@pytest.mark.asyncio
async def test_shared_executor_excludes_voice_and_releases_on_cancel(monkeypatch,tmp_path):
    monkeypatch.setattr(L,'ROOT',tmp_path)
    monkeypatch.setenv('DAN_BROWSER_ROOM','shared')
    entered=asyncio.Event()
    async def worker():
        async with L.operation('browser_script'):
            entered.set();await asyncio.Event().wait()
    task=asyncio.create_task(worker());await entered.wait()
    with pytest.raises(L.BrowserBusy):
        async with L.operation('browser',timeout=.03):
            pytest.fail('concurrent action')
    # Another browser remains usable.
    monkeypatch.setenv('DAN_BROWSER_ROOM','other')
    async with L.operation('browser',timeout=0):pass
    monkeypatch.setenv('DAN_BROWSER_ROOM','shared')
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    async with L.operation('browser',timeout=0):pass
