"""Steerable production through the ChatGPT-authenticated Codex CLI.

Native shell, web and the ordinary Dan MCP servers remain available. Updates
arrive during research too, without killing a turn or restarting a paid job.
"""
import asyncio
import json
import time
from pathlib import Path

from app.services.editor_codex import CodexTurn

_owners = {}


def close_owner(owner):
    # app-server owns persistent MCP subprocesses; reap only this turn's tree.
    import psutil
    try:
        children = psutil.Process(owner.process.pid).children(recursive=True)
    except psutil.Error:
        children = []
    owner.close()
    for child in reversed(children):
        try:
            child.terminate()
        except psutil.Error:
            pass


def cancel(room, content):
    owner = _owners.get((room, content))
    if owner:
        close_owner(owner)


def tool_event(item):
    kind = item.get('type')
    name, args = None, {}
    if kind == 'mcpToolCall':
        name = 'mcp__' + item['server'] + '__' + item['tool']
        args = item.get('arguments') or {}
    elif kind == 'commandExecution':
        name, args = 'Bash', {'command': item.get('command', '')}
    elif kind == 'webSearch':
        name, args = 'WebSearch', {'query': item.get('query', '')}
    elif kind == 'fileChange':
        name, args = 'Edit', {'changes': item.get('changes', [])}
    if name:
        return {'id': item['id'], 'name': name, 'input': args}


async def run(room, content, job, prompt, system, mcp_path, model, emit):
    from app.services import editor_job_updates as updates, timeline_draft as td
    owner = CodexTurn()
    _owners[(room, content)] = owner
    folder = td._room_dir(room) / 'jobs' / job
    inflight = {}
    retry_after = {}
    messages = []
    receive_task = None
    try:
        await owner.rpc('initialize', {'clientInfo': {'name': 'dan_production', 'version': '2'},
                                      'capabilities': {'experimentalApi': True}})
        owner.send({'method': 'initialized'})
        account = await owner.rpc('account/read', {})
        if (account.get('account') or {}).get('type') not in ('chatgpt', 'chatgptAuthTokens'):
            raise RuntimeError('Production requires ChatGPT CLI authentication')
        servers = json.loads(Path(mcp_path).read_text(encoding='utf-8')).get('mcpServers', {})
        servers = {name: {**cfg, 'startup_timeout_sec': 60, 'tool_timeout_sec': 1800}
                   for name, cfg in servers.items() if isinstance(cfg, dict)}
        config = {'model_reasoning_effort': 'high', 'web_search': 'live', 'mcp_servers': servers}
        thread = await owner.rpc('thread/start', {
            'model': model, 'cwd': str(Path(__file__).resolve().parents[2]),
            'approvalPolicy': 'never', 'sandbox': 'danger-full-access',
            'developerInstructions': system, 'config': config,
        })
        owner.thread_id = thread['thread']['id']
        (folder / 'codex-thread.json').write_text(json.dumps({'thread_id': owner.thread_id}), encoding='utf-8')
        turn = await owner.rpc('turn/start', {'threadId': owner.thread_id,
                                           'input': [{'type': 'text', 'text': prompt}]})
        owner.turn_id = turn['turn']['id']
        emit({'type': 'status', 'text': '制作担当が接続しました。追加指示を作業中に受け取れます。'})
        while True:
            # The event loop services steering even while a shell/MCP call runs.
            for row in updates.pending(room, job):
                if row['id'] in {r['id'] for r in inflight.values()}:
                    continue
                if retry_after.get(row['id'], 0) > time.monotonic():
                    continue
                owner.serial += 1
                rid = owner.serial
                owner.send({'id': rid, 'method': 'turn/steer', 'params': {
                    'threadId': owner.thread_id, 'expectedTurnId': owner.turn_id,
                    'input': [{'type': 'text', 'text': row['instruction']}]}})
                inflight[rid] = row
                emit({'type': 'instruction_forwarded', 'update_id': row['id'], 'submitted_at': row['at']})
            if receive_task is None:
                # A render/service call can legitimately run beyond the short
                # conversation timeout. Its MCP timeout owns that deadline;
                # keep accepting steering while the event queue is quiet.
                receive_task = asyncio.create_task(asyncio.to_thread(owner.events.get))
            done, _ = await asyncio.wait([receive_task], timeout=.2)
            if not done:
                continue
            event = receive_task.result()
            receive_task = None
            if event.get('id') in inflight and 'method' not in event:
                row = inflight.pop(event['id'])
                if 'error' not in event:
                    receipt = folder / 'instructions' / (row['id'] + '.received')
                    receipt.write_text(str(time.time()))
                    emit({'type': 'instruction_received', 'update_id': row['id'],
                          'latency_ms': round((time.time() - row['at']) * 1000)})
                else:
                    # Durable pending file is retained for the next turn/tool.
                    emit({'type': 'instruction_delivery_failed', 'update_id': row['id'], 'error': event['error']})
                    retry_after[row['id']] = time.monotonic() + 2
                continue
            method, params = event.get('method'), event.get('params', {})
            if method in ('item/started', 'item/completed'):
                item = params.get('item', {})
                tool = tool_event(item)
                if tool:
                    if method == 'item/started':
                        emit({'type': 'tool_use', **tool})
                    emit({'type': 'tool_progress', **tool,
                          'state': 'running' if method == 'item/started' else
                                   'failed' if item.get('status') == 'failed' else 'done'})
                elif method == 'item/completed' and item.get('type') == 'agentMessage':
                    text = item.get('text', '')
                    messages.append(text)
                    emit({'type': 'text', 'text': text})
            elif method == 'turn/completed':
                if updates.pending(room, job):
                    inflight.clear()
                    turn = await owner.rpc('turn/start', {'threadId': owner.thread_id, 'input': [
                        {'type': 'text', 'text': '追加指示が届いています。保存済みの成果を引き継いで続けてください。'}]})
                    owner.turn_id = turn['turn']['id']
                    continue
                failed = params.get('turn', {}).get('status') != 'completed'
                return {'is_error': failed, 'text': '\n'.join(messages), 'thread_id': owner.thread_id}
            elif 'id' in event and method:
                owner.send({'id': event['id'], 'error': {'code': -32601,
                    'message': 'Unsupported client request. Use the available timeline tools for user questions.'}})
            elif method == 'process/closed':
                raise RuntimeError('Production CLI connection closed')
            elif method == 'error':
                emit({'type': 'error', 'message': str(params.get('error', params))})
    finally:
        close_owner(owner)
        if receive_task:
            receive_task.cancel()
        _owners.pop((room, content), None)
