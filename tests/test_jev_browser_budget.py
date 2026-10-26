import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.services import jev_browser_budget as budget


@pytest.fixture
def ledger(monkeypatch,tmp_path):
    monkeypatch.setattr(budget,'PATH',tmp_path/'budget.json')
    monkeypatch.delenv('DAN_JEV_BROWSER_ENABLED',raising=False)
    def write(**kwargs):
        data={'enabled':True,'publish':True,'user_id':'owner','approved_usd':3,'reserved_usd':0,'requests':0,'max_requests':200,**kwargs}
        budget.PATH.write_text(json.dumps(data),encoding='utf-8')
    return write


def test_missing_corrupt_or_wrong_owner_never_reserves(ledger):
    assert not budget.enabled() and not budget.reserve({},'owner')
    budget.PATH.write_text('not json')
    assert not budget.enabled() and not budget.reserve({},'owner')
    ledger()
    assert not budget.reserve({},'other')
    assert budget.read()['requests']==0


def test_concurrent_workers_cannot_exceed_ceiling(ledger):
    ledger(max_requests=5)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda _:budget.reserve({'private':'never store this'},'owner'),range(24)))
    assert sum(results)==5
    saved=budget.read()
    assert saved['requests']==5 and 0<saved['reserved_usd']<3
    assert 'never store this' not in budget.PATH.read_text()
    assert not budget.enabled()


def test_dollar_cap_and_disabled_are_fail_closed(ledger):
    ledger(approved_usd=.000001)
    assert not budget.reserve({},'owner')
    ledger(enabled=False)
    assert not budget.enabled() and not budget.reserve({},'owner')
    ledger(approved_usd=float('nan'))
    assert not budget.enabled() and not budget.reserve({},'owner')


@pytest.mark.asyncio
async def test_client_checks_budget_before_network(ledger,monkeypatch):
    from app.services.jev_decisions import Decisions
    from unittest.mock import AsyncMock
    monkeypatch.setattr(Decisions,'_credential',AsyncMock(return_value='test-key'))
    async with Decisions('owner',enabled=True) as client:
        result=await client.choose({}, {'q':{'type':'choice','criteria':{'yes':'Yes','no':'No'}}})
        assert result['reason']=='approved_budget_unavailable'
        assert client.calls==0 and client._client is None

@pytest.mark.asyncio
async def test_call_recovers_later_after_timeout_but_never_auth_or_budget_denial(ledger,monkeypatch):
    import httpx
    from app.services.jev_decisions import Decisions
    from unittest.mock import AsyncMock
    ledger()
    monkeypatch.setattr(Decisions,'_credential',AsyncMock(return_value='fixture-key'))
    questions={'q':{'type':'choice','criteria':{'yes':'y','no':'n'}}}
    calls=[]
    async def respond(request):
        calls.append(request)
        if len(calls)==1:raise httpx.ReadTimeout('fixture')
        return httpx.Response(200,json={'answers':{'q':{'type':'choice','choice':'yes','confidence':1,'probabilities':{'yes':1,'no':0}}}})
    async with Decisions('owner',enabled=True,retry_transient_after=10) as client:
        client._client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        assert not (await client.choose({},questions))['available']
        assert not (await client.choose({},questions))['available'] and len(calls)==1
        client.retry_at=0
        assert (await client.choose({},questions))['available'] and len(calls)==2
    async with Decisions('owner',enabled=True,retry_transient_after=0) as client:
        client._client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(401)))
        assert not (await client.choose({},questions))['available']
        assert client.retry_at is None
        assert not (await client.choose({},questions))['available'] and client.calls==1
    async with Decisions('other',enabled=True,retry_transient_after=0) as client:
        assert not (await client.choose({},questions))['available']
        assert client.retry_at is None and client.calls==0

@pytest.mark.asyncio
async def test_transient_recovery_is_bounded_across_a_long_call(ledger,monkeypatch):
    import httpx
    from app.services.jev_decisions import Decisions
    from unittest.mock import AsyncMock
    ledger();monkeypatch.setattr(Decisions,'_credential',AsyncMock(return_value='fixture'))
    def timeout(request):raise httpx.ReadTimeout('fixture')
    async with Decisions('owner',enabled=True,retry_transient_after=0) as client:
        client._client=httpx.AsyncClient(transport=httpx.MockTransport(timeout))
        for _ in range(20):assert not (await client.choose({}, {'q':{'type':'choice','criteria':{'y':'y','n':'n'}}}))['available']
        assert client.calls==3 and client.recoveries==2
