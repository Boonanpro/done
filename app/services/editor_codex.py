"""Editor tool turns through Codex app-server, authenticated with ChatGPT.

Dynamic tools keep the existing editor transaction/UI path intact. A Codex
turn stays alive while the browser executes a tool and returns its result.
No Responses API client or API-key fallback exists in this adapter.
"""
from __future__ import annotations

import asyncio
import atexit
import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

_pending = {}
_processes = set()
_active = {}


class CodexTurn:
    def __init__(self):
        from app.agent.codex_runner import resolve_codex_cli
        executable = resolve_codex_cli()
        if not executable:
            raise RuntimeError('Codex CLIが見つかりません。APIへは切り替えていません。')
        env = dict(os.environ)
        for key in ('OPENAI_API_KEY', 'CODEX_API_KEY'):
            env.pop(key, None)
        self.process = subprocess.Popen(
            [executable, '-c', 'forced_login_method="chatgpt"', '-c', 'model_provider="openai"', 'app-server', '--stdio'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        self.events = queue.Queue()
        self.replies = {}
        self.serial = 0
        self.timer = None
        self.thread_id = None
        self.turn_id = None
        self.steering = []
        self.output = []
        self.usage = None
        self.closed = False
        _processes.add(self)
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        try:
            for line in self.process.stdout:
                try:
                    event = json.loads(line)
                    waiter = self.replies.get(event.get('id')) if 'method' not in event else None
                    (waiter if waiter is not None else self.events).put(event)
                except ValueError:
                    continue
        finally:
            self.events.put({'method': 'process/closed'})

    def send(self, value):
        self.process.stdin.write((json.dumps(value, ensure_ascii=False) + '\n').encode())
        self.process.stdin.flush()

    async def receive(self):
        try:
            return await asyncio.to_thread(self.events.get, True, getattr(self, 'receive_timeout', 120))
        except queue.Empty:
            raise RuntimeError('Codex CLIの応答がタイムアウトしました。APIへは切り替えていません。')

    async def request_concurrent(self, method, params):
        """Read an acknowledgement without stealing events from the active turn."""
        self.serial += 1
        request_id = self.serial
        waiter = queue.Queue()
        self.replies[request_id] = waiter
        try:
            self.send({'id': request_id, 'method': method, 'params': params})
            try:
                return await asyncio.to_thread(waiter.get, True, 10)
            except queue.Empty:
                raise RuntimeError('追加指示の受信確認が取れません。自動再送はしていません。')
        finally:
            self.replies.pop(request_id, None)

    async def rpc(self, method, params):
        self.serial += 1
        request_id = self.serial
        self.send({'id': request_id, 'method': method, 'params': params})
        deferred = []
        while True:
            event = await self.receive()
            if event.get('id') == request_id and 'method' not in event:
                for notification in deferred:
                    self.events.put(notification)
                if 'error' in event:
                    raise RuntimeError('Codex CLI: ' + str(event['error'].get('message', 'request failed')))
                return event['result']
            if event.get('method') == 'process/closed':
                raise RuntimeError('Codex CLIが終了しました。')
            deferred.append(event)

    async def prepare(self, tools, instructions, model, *, config_overrides=None, sandbox='read-only'):
        await self.rpc('initialize', {'clientInfo': {'name': 'dan_editor', 'version': '1.0'},
                                     'capabilities': {'experimentalApi': True}})
        self.send({'method': 'initialized'})
        account = await self.rpc('account/read', {})
        if (account.get('account') or {}).get('type') not in ('chatgpt', 'chatgptAuthTokens'):
            raise RuntimeError('CodexをChatGPT契約でログインしてください。APIキー課金では実行しません。')
        dynamic = [{'type': 'function', 'name': t['name'], 'description': t['description'],
                    'inputSchema': t['parameters']} for t in tools if t.get('type') == 'function']
        started = await self.rpc('thread/start', {
            'model': model, 'cwd': str(Path(__file__).resolve().parents[2]),
            'approvalPolicy': 'never', 'sandbox': sandbox, 'ephemeral': True,
            'developerInstructions': instructions,
            'dynamicTools': dynamic,
            'config': {'model_reasoning_effort': 'high', 'web_search': 'live' if any(t.get('type')=='web_search' for t in tools) else 'disabled', **(config_overrides or {})},
        })
        self.thread_id = started['thread']['id']
        self.service_tier = started.get('serviceTier')

    async def start(self, inputs, tools, instructions, model, *, config_overrides=None, sandbox='read-only'):
        await self.prepare(tools,instructions,model,config_overrides=config_overrides,sandbox=sandbox)
        text_inputs = []
        images = []
        for row in inputs:
            row = dict(row)
            if isinstance(row.get('content'), list):
                content = []
                for part in row['content']:
                    if part.get('type') == 'input_image':
                        images.append({'type': 'image', 'url': part['image_url']})
                    else:
                        content.append(part)
                row['content'] = content
            text_inputs.append(row)
        started_turn=await self.rpc('turn/start', {'threadId': self.thread_id,
            'input': [{'type': 'text', 'text': '会話原文・画面情報・既存の道具の結果です。役割を保持して読んでください。\n' + json.dumps(text_inputs, ensure_ascii=False)}] + images})
        self.turn_id=started_turn['turn']['id']
        for text in self.steering:
            self.steer(text)
        self.steering.clear()

    def steer(self,text):
        if not self.turn_id:
            self.steering.append(text)
            return
        self.serial+=1
        self.send({'id':self.serial,'method':'turn/steer','params':{
            'threadId':self.thread_id,'expectedTurnId':self.turn_id,
            'input':[{'type':'text','text':text}]}})

    def close(self):
        if self.closed:
            return
        self.closed = True
        for key,owner in list(_active.items()):
            if owner is self:_active.pop(key,None)
        if self.timer:
            self.timer.cancel()
        for key, (owner, _) in list(_pending.items()):
            if owner is self:
                _pending.pop(key, None)
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        self.process.stdin.close()
        _processes.discard(self)


def close_all():
    for process in list(_processes):
        process.close()


def cancel_pending(calls):
    for call in calls:
        suspended = _pending.get(call.get('call_id'))
        if suspended:
            suspended[0].close()


def cancel_active(key):
    owner=_active.get(key)
    if owner:owner.close()


def steer_active(key,text):
    owner=_active.get(key)
    if not owner or owner.closed:return False
    owner.steer(text)
    return True


atexit.register(close_all)


async def stream_response(inputs, tools, instructions, model, run_key=None):
    # The endpoint passes the accumulated turn. Only its trailing tool result
    # identifies a suspended Codex request; old results must never be replayed.
    trailing = next((r for r in reversed(inputs) if r.get('type') == 'function_call_output'), None)
    suspended = _pending.pop(trailing['call_id'], None) if trailing else None
    owner = suspended[0] if suspended else CodexTurn()
    if run_key:_active[run_key]=owner
    paused = False
    started_at=time.monotonic()
    try:
        if suspended:
            owner.timer.cancel()
            content = [{'type': 'inputText', 'text': trailing['output']}]
            index = inputs.index(trailing)
            for row in inputs[index + 1:]:
                for part in row.get('content', []) if isinstance(row.get('content'), list) else []:
                    if part.get('type') == 'input_image':
                        content.append({'type': 'inputImage', 'imageUrl': part['image_url']})
            owner.send({'id': suspended[1], 'result': {'success': True, 'contentItems': content}})
        else:
            if trailing and str(trailing['call_id']).startswith('codex-editor-'):
                raise RuntimeError('Codexの実行接続が終了しました。実行済みの操作は再実行せず、会話を再開してください。')
            yield {'type':'progress','phase':'connecting','text':'編集担当を起動しています','elapsed_ms':0}
            # Short editor turns have explicit application tools. Native workspace
            # tools belong to the separately delegated production worker.
            config_path=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'config.toml'
            names=re.findall(r'^\[mcp_servers\.([^\].]+)\]',config_path.read_text(encoding='utf-8'),re.M) if config_path.exists() else []
            # Interactive previews already have an editor runtime. Do not
            # implicitly route every small revision through project creation.
            # Explicit read_skill remains available; production workers keep
            # their normal skill configuration.
            preview_skills=[{'path':str(p),'enabled':False} for root in
                (Path.home()/'.agents'/'skills',config_path.parent/'skills')
                for p in root.glob('hyperframes*/SKILL.md')]
            await owner.start(inputs, tools, instructions, model,config_overrides={
                'features.shell_tool':False,
                'features.fast_mode':True,
                'service_tier':os.environ.get('DAN_EDITOR_SERVICE_TIER','fast') or None,
                'model_reasoning_effort':os.environ.get('DAN_EDITOR_TOOL_REASONING_EFFORT','medium'),
                'skills.config':preview_skills,
                'mcp_servers':{name.strip('"'):{'enabled':False} for name in names}})
            yield {'type':'progress','phase':'thinking','text':'考えています','service_tier':getattr(owner,'service_tier',None),'elapsed_ms':round((time.monotonic()-started_at)*1000)}
        output = []
        while True:
            event = await owner.receive()
            method, params = event.get('method'), event.get('params', {})
            if method == 'item/agentMessage/delta':
                yield {'type': 'text', 'delta': params['delta']}
            elif method in {'item/started','item/completed'} and params.get('item',{}).get('type') in {'commandExecution','webSearch'}:
                kind=params['item']['type']
                yield {'type':'progress','phase':'tool' if method=='item/started' else 'thinking',
                    'text':('ファイル・実装を調べています' if kind=='commandExecution' else 'Webで情報を探しています') if method=='item/started' else '取得した情報を基に判断しています',
                    'elapsed_ms':round((time.monotonic()-started_at)*1000)}
            elif method is None and event.get('error'):
                yield {'type':'progress','phase':'update_failed','text':'追加発言の受け渡しを確認しています','error':event['error']}
            elif method == 'item/completed' and params.get('item', {}).get('type') == 'agentMessage':
                yield {'type': 'message_complete', 'id': params['item'].get('id'),
                       'phase': params['item'].get('phase'), 'text': params['item']['text']}
                output.append({'type': 'message', 'role': 'assistant',
                               'content': [{'type': 'output_text', 'text': params['item']['text']}]})
            elif method == 'item/tool/call':
                call_id = 'codex-editor-' + uuid.uuid4().hex
                _pending[call_id] = (owner, event['id'])
                output.append({'type': 'function_call', 'call_id': call_id, 'name': params['tool'],
                               'arguments': json.dumps(params['arguments'], ensure_ascii=False)})
                owner.timer = threading.Timer(120, owner.close)
                owner.timer.daemon = True
                owner.timer.start()
                paused = True
                yield {'type': 'completed', 'output': output, 'usage': None,
                       'backend': 'codex_cli', 'billing': 'chatgpt_plan', 'thread_id': owner.thread_id}
                return
            elif method == 'turn/completed':
                turn = params['turn']
                if turn['status'] != 'completed':
                    raise RuntimeError('Codex CLI: ' + str(turn.get('error') or turn['status']))
                yield {'type': 'completed', 'output': output, 'usage': None,
                       'backend': 'codex_cli', 'billing': 'chatgpt_plan', 'thread_id': owner.thread_id}
                return
            elif method == 'process/closed':
                raise RuntimeError('Codex CLIが処理中に終了しました。')
            elif 'id' in event and method:
                owner.send({'id': event['id'], 'error': {'code': -32601, 'message': 'Use the provided editor tools for this operation.'}})
    finally:
        if not paused:
            owner.close()
