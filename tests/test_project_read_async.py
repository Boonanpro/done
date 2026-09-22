import threading
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from app.services.project_service import ProjectService


@pytest.mark.asyncio
async def test_project_lookup_does_not_run_blocking_transport_on_event_loop():
    caller=threading.get_ident();threads=[]
    service=object.__new__(ProjectService);service.supabase=MagicMock()
    def execute():
        threads.append(threading.get_ident())
        return SimpleNamespace(data=[{'id':'project'}])
    service.supabase.table.return_value.select.return_value.eq.return_value.execute.side_effect=execute
    assert await service.get_project_by_room_id('room')=={'id':'project'}
    assert threads and threads[0]!=caller


@pytest.mark.asyncio
async def test_late_heartbeat_cannot_reopen_completed_run():
    from app.services.run_service import RunService
    saved={'id':'run','state':'running'}
    class Query:
        allowed=None
        def update(self,updates):self.updates=updates;return self
        def eq(self,*args):return self
        def in_(self,field,values):self.allowed=values;return self
        def execute(self):
            # Completion wins before a delayed heartbeat reaches the database.
            saved['state']='completed'
            if self.allowed is not None and saved['state'] not in self.allowed:
                return SimpleNamespace(data=[])
            saved.update(self.updates);return SimpleNamespace(data=[saved])
    service=object.__new__(RunService);service.supabase=MagicMock()
    service.supabase.table.return_value=Query()
    assert await service.update_run('run',state='running',only_if_active=True) is None
    assert saved['state']=='completed'
