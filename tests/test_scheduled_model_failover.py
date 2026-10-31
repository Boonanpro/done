import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.agent import subscription_text as text, provider_failover as pf, turn_dispatch as dispatch


@pytest.fixture(autouse=True)
def limits():
    pf._blocked.clear()
    yield
    pf._blocked.clear()


@pytest.mark.parametrize('model,first,second', [('opus','claude','codex'), ('gpt-6-astra','codex','claude')])
def test_text_quota_switches_once_with_same_source(monkeypatch, model, first, second):
    calls=[]
    def run(backend):
        def invoke(prompt, **kwargs):
            calls.append((backend,prompt))
            if backend==first:raise text.UsageLimitError('weekly limit')
            return 'answer'
        return invoke
    monkeypatch.setattr(text,'codex_text',run('codex'))
    assert text.generate('source',model,60,None,run('claude'))=='answer'
    assert calls==[(first,'source'),(second,'source')]


def test_both_exhausted_are_not_retried_by_json_generation(monkeypatch):
    calls=[]
    def fail(*args,**kwargs):
        calls.append(1);raise text.UsageLimitError('weekly limit')
    monkeypatch.setattr(text,'codex_text',fail)
    assert text.generate('source','opus',60,None,fail) is None
    assert text.generate('source','opus',60,None,fail) is None
    assert len(calls)==2


def test_nonquota_failure_does_not_switch(monkeypatch):
    codex=Mock();monkeypatch.setattr(text,'codex_text',codex)
    assert text.generate('source','opus',60,None,lambda *a,**k:None) is None
    codex.assert_not_called()


def test_only_shared_core_dispatches_to_release(monkeypatch,tmp_path):
    from app.services import room_feed
    monkeypatch.setattr(dispatch.G,'ROOT',tmp_path)
    (tmp_path/'enabled').touch()
    monkeypatch.setattr(dispatch.G,'read',lambda name:{'core':9218})
    monkeypatch.setattr(room_feed,'in_core_process',lambda:True)
    monkeypatch.delenv('DAN_GENERATION',raising=False)
    assert dispatch.remote_required()
    monkeypatch.setenv('DAN_GENERATION','release')
    assert not dispatch.remote_required()
    monkeypatch.delenv('DAN_GENERATION')
    monkeypatch.setattr(room_feed,'in_core_process',lambda:False)
    assert not dispatch.remote_required()


@pytest.mark.asyncio
async def test_dispatch_failure_releases_reservation_without_retry(monkeypatch):
    monkeypatch.setattr(dispatch.G,'reserve_room',lambda room:({'core':9218},'token'))
    release=Mock();monkeypatch.setattr(dispatch.G,'release_room',release)
    requests=[]
    class Client:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def stream(self,*args,**kwargs):
            requests.append((args,kwargs));raise dispatch.httpx.ConnectError('offline')
    monkeypatch.setattr(dispatch.httpx,'AsyncClient',lambda **kwargs:Client())
    with pytest.raises(dispatch.httpx.ConnectError):
        async for event in dispatch.relay({'room_id':'room','user_id':'owner','content':'continue'}):pass
    assert len(requests)==1
    release.assert_called_once_with('room','token')


def test_scheduled_writer_reads_room_model_each_time(monkeypatch):
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
    import denki_seo_engines as seo
    from app.agent import cli_runner as cr
    chosen=iter([('gpt-6-astra','codex'),('gpt-6.1-terra','codex')])
    monkeypatch.setattr(cr,'resolve_room_backend',lambda room:next(chosen))
    run=Mock(return_value='answer');monkeypatch.setattr(cr,'run_oneshot_cli',run)
    assert seo.claude('first')=='answer'
    assert seo.claude('second')=='answer'
    assert [call.kwargs['model'] for call in run.call_args_list]==['gpt-6-astra','gpt-6.1-terra']
