import asyncio
import time
from unittest.mock import Mock

import pytest

from app.agent import cli_runner as runner, codex_runner


@pytest.mark.asyncio
async def test_preparation_keeps_exact_context_and_does_not_block_other_rooms(monkeypatch):
    def build(**kwargs):
        time.sleep(.15)
        return 'CURRENT:'+kwargs['latest_user_message']
    def config(room, user, credentials):
        time.sleep(.15)
        return 'config:'+room
    monkeypatch.setattr(runner, '_build_system_prompt', build)
    monkeypatch.setattr(runner, '_build_mcp_config', config)
    ticks=[]
    async def heartbeat():
        for _ in range(8):
            await asyncio.sleep(.01)
            ticks.append(time.perf_counter())
    started=time.perf_counter()
    result, _ = await asyncio.gather(runner._prepare_cli_inputs('room','user',None,None,None,
        {'latest_user_message':'new correction'}), heartbeat())
    assert result == ['CURRENT:new correction','config:room']
    assert ticks[0]-started < .1
    assert ticks[-1]-started < .15


@pytest.mark.asyncio
async def test_explicit_inputs_skip_builders(monkeypatch):
    prompt=Mock(side_effect=AssertionError('explicit prompt'))
    config=Mock(side_effect=AssertionError('explicit MCP'))
    monkeypatch.setattr(runner,'_build_system_prompt',prompt)
    monkeypatch.setattr(runner,'_build_mcp_config',config)
    assert await runner._prepare_cli_inputs('r','u',None,'custom','custom.json',{}) == ['custom','custom.json']
    prompt.assert_not_called();config.assert_not_called()


def test_assembled_current_context_reaches_resumed_codex_turn(monkeypatch):
    from app.agent import bootstrap_context as bootstrap
    monkeypatch.setattr(bootstrap,'load_all_bootstrap_files',lambda:'Current user rules')
    monkeypatch.setattr(bootstrap,'load_artifact_descriptions',lambda **kwargs:'')
    monkeypatch.setattr(bootstrap,'load_artifact_publish_state',lambda **kwargs:'')
    prompt=runner._build_system_prompt('','','in_progress',latest_user_message='Continue')
    assert 'browser_plan' in prompt and 'needs_agent' in prompt and 'observation=dom' in prompt
    wrapped=codex_runner.wrap_turn_content(prompt,'Continue')
    assert 'browser_plan' in wrapped and 'Current user rules' in wrapped
