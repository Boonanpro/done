"""Exercise real PostgREST request encoding with an entirely local transport."""
import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from postgrest import SyncPostgrestClient

from app.services.run_service import RunService


@pytest.mark.asyncio
@pytest.mark.parametrize('initial', [None, {}, {'memo': '日本語'}])
@pytest.mark.parametrize('writer', ['progress', 'stop'])
async def test_metadata_merge_keeps_concurrent_stop_and_progress(initial, writer):
    row = {'id': 'run', 'state': 'running', 'metadata': initial}
    patches = []
    stop = {'at': 'now', 'stopped': False}

    def handle(request):
        assert request.url.params['id'] == 'eq.run'
        if request.method == 'GET':
            return httpx.Response(200, json=[copy.deepcopy(row)])
        assert request.method == 'PATCH'
        patches.append(request)
        if len(patches) == 1:
            row['metadata'] = {**(row['metadata'] or {}),
                               **({'stop_request': stop} if writer == 'progress' else {'progress': '途中'})}
        condition = request.url.params['metadata']
        matched = (row['metadata'] is None if condition == 'is.null' else
                   row['metadata'] == json.loads(condition.removeprefix('eq.')))
        if not matched:
            return httpx.Response(200, json=[])
        row.update(json.loads(request.content))
        return httpx.Response(200, json=[copy.deepcopy(row)])

    with httpx.Client(transport=httpx.MockTransport(handle), base_url='http://local.test') as http:
        client = SyncPostgrestClient('http://local.test', http_client=http)
        service = RunService.__new__(RunService)
        service.supabase = SimpleNamespace(table=client.from_)
        result = await service.update_run('run', metadata=(
            {'progress': '途中'} if writer == 'progress' else {'stop_request': stop}))
        assert result['metadata']['stop_request'] == stop
        assert result['metadata']['progress'] == '途中'
        assert len(patches) == 2
        # A stale full snapshot cannot remove a receipt even without a race.
        result = await service.update_run('run', metadata={'stop_request': None})
        assert result['metadata']['stop_request'] == stop


@pytest.mark.asyncio
async def test_persistent_conflict_is_bounded_and_never_claimed_saved():
    patches = []
    def handle(request):
        if request.method == 'GET':
            return httpx.Response(200, json=[{'id': 'run', 'state': 'running', 'metadata': {}}])
        patches.append(request)
        return httpx.Response(200, json=[])
    with httpx.Client(transport=httpx.MockTransport(handle), base_url='http://local.test') as http:
        client = SyncPostgrestClient('http://local.test', http_client=http)
        service = RunService.__new__(RunService)
        service.supabase = SimpleNamespace(table=client.from_)
        with pytest.raises(RuntimeError, match='保存を確認'):
            await service.update_run('run', metadata={'stop_request': {'stopped': False}})
        assert len(patches) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize('row', [None, {'id': 'run', 'state': 'completed', 'metadata': {}}])
async def test_missing_or_inactive_run_does_not_retry_or_write(row):
    def handle(request):
        assert request.method == 'GET'
        return httpx.Response(200, json=[row] if row else [])
    with httpx.Client(transport=httpx.MockTransport(handle), base_url='http://local.test') as http:
        client = SyncPostgrestClient('http://local.test', http_client=http)
        service = RunService.__new__(RunService)
        service.supabase = SimpleNamespace(table=client.from_)
        assert await service.update_run('run', metadata={'progress': 'late'}, only_if_active=True) is None
