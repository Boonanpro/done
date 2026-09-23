"""A job run by the API: GPT-5.6 through the Responses API in this worker process, with Dan's own tools called directly.

Why (2026-09-23): a job through the Codex CLI spent 20-60 seconds before its first browser action (CLI start, MCP
handshake, context prefill) and paid a CLI turn per step; for a two-minute job that is half the time. Here the model
call starts within about two seconds of the job, and each step costs one API round trip. The job's state file, the
steering (steer_job), the confirmation gate, the tool events and the result delivery are the same as for a CLI job:
this process only replaces the model loop.

Usage (spawned by api_job_runner with the job's environment): python -m app.services.api_job_worker <job_id>
"""
import asyncio
import json
import os
import sys
import time

# Read when used (after .env is loaded), not at import.
MODEL = lambda: os.environ.get('DAN_API_JOB_MODEL', 'deepseek-flash')   # 2026-09-23 comparison: all three tasks right, fastest and 1/27 of Astra's cost (see docs/current/job-model-comparison-20260923.md)
REASONING = lambda: os.environ.get('DAN_API_JOB_REASONING', 'low')
MAX_TURNS = 120
# The tools a job needs. The MCP list carries 33 tools (56k characters of schema) for the CLI; sending all of them on every
# call made a step 6-8s (2026-09-23 15:11). DAN_API_JOB_TOOLS=all sends the whole list.
JOB_TOOLS = lambda: os.environ.get('DAN_API_JOB_TOOLS', 'browser,browser_script,flow,desktop,lookup,get_credentials,save_credentials,get_personal_info,'
                                   'get_location,read_url,bash,read_file,write_file,wait_until,job_confirmation,job_progress,command_center').split(',')
OUTPUT_CHARS = 12000
CONTINUATION = ('本人の返事を受け付けた現在の作業状態です。確定操作はまだ実行していません。画面を読み取り、承認済みの具体的な操作だけを再開してください。'
                '条件変更があれば以前の承認は無効です。\n')


def job_tools(mcp_tools):
    """The MCP tool list as provider-neutral function tools (the job's subset)."""
    out = []
    for tool in mcp_tools:
        if JOB_TOOLS() != ['all'] and tool.name not in JOB_TOOLS(): continue
        out.append({'name': tool.name, 'description': (tool.description or '')[:1024], 'parameters': dict(tool.inputSchema or {'type': 'object', 'properties': {}})})
    return out


_SECRET = ('pass', 'secret', 'token', 'card', 'cvv', 'otp', 'code', 'pin')


def trace_step(call, output, images, seconds):
    """One line per tool call in the job's work folder (steps.jsonl): which steps a model spends and on what. Values of
    secret-looking keys, and everything typed into credentials, are masked."""
    folder = os.environ.get('DAN_WORK_DIR')
    if not folder:
        return
    raw = call.get('args') or {}
    private = call['name'] in ('save_credentials', 'get_credentials', 'get_personal_info')
    typed = str(raw.get('action')) in ('type', 'fill', 'keys')   # what was typed may be a password
    args = {k: ('***' if private or any(w in k.lower() for w in _SECRET) or (typed and k in ('text', 'value', 'keys'))
                else str(v)[:300]) for k, v in raw.items()}
    try:
        with open(os.path.join(folder, 'steps.jsonl'), 'a', encoding='utf-8') as f:
            f.write(json.dumps({'name': call['name'], 'args': args, 'output_chars': len(output), 'images': len(images),
                                'seconds': round(seconds, 2), 'head': '***' if private else output[:200]}, ensure_ascii=False) + '\n')
    except OSError:
        pass


def function_output(contents):
    """What the model reads back: the texts joined (capped), and images as data URLs."""
    texts, images = [], []
    for c in contents:
        if getattr(c, 'type', '') == 'text': texts.append(c.text)
        elif getattr(c, 'type', '') == 'image': images.append(f'data:{c.mimeType};base64,{c.data}')
    return chr(10).join(texts)[:OUTPUT_CHARS] or '（出力なし）', images


class Worker:
    def __init__(self, job_id):
        from app.services import command_job_state as state
        self.state, self.job_id = state, job_id
        self.applied = 0
        self.client = None

    def read(self):
        return self.state.read(self.job_id) or {}

    def new_inputs(self):
        """Steering that arrived (steer_job update): applied here by feeding it to the model, and marked applied."""
        s = self.read()
        fresh = [i for i in s.get('inputs', []) if i['revision'] > s.get('applied_revision', 0)]
        if fresh:
            top = max(i['revision'] for i in fresh)
            def applied(st):
                st['applied_revision'] = max(st.get('applied_revision', 0), top)
                self.state.event(st, 'applied', '追加指示を実行担当が受け取りました')
            self.state.change(self.job_id, applied)
        return fresh

    async def replay(self, spec):
        """A remembered operation, replayed by code before the model starts (the voice backend chose it): in this job's
        browser and with the owner's id, so a moved element can be re-found by Jev. Returns the note the model starts from."""
        from app.services.browser_flows import all_flows, run
        flow = next((f for f in all_flows() if f['id'] == spec.get('id')), None)
        if not flow:
            return '（記憶した手順が見つからなかった。通常どおり作業する）'
        self.state.publish(self.job_id, 'progress', '記憶した手順を再生しています')
        try:
            outcome = await run(flow, spec.get('values') or {})
        except Exception as exc:
            outcome = {'replayed': False, 'reason': type(exc).__name__}
        if not outcome.get('replayed'):
            return f"（記憶した手順の再生は途中で止まった: {str(outcome.get('reason') or '')[:80]}。今の画面から通常どおり続ける）"
        from app.agent.v2.tools import _execute_browser_tool
        page = await _execute_browser_tool('read', {'max_chars': 4000})
        text = ' '.join(b.get('text', '') for b in page.get('content', []) if b.get('type') == 'text')[:4000]
        return ('記憶した手順を再生済み（' + str(outcome.get('elapsed_ms')) + 'ms）。今の画面:\n' + text +
                '\nこの画面で依頼に答えられればそのまま答える。足りなければ続けて操作する。')

    async def run(self):
        from app.mcp_server import list_tools, call_tool
        from app.services import api_job_providers
        s = self.read()
        model = s.get('model') or MODEL()
        provider = api_job_providers.make(model)
        first = list(s.get('history', [])) + [s['task']]
        if s.get('replay'):
            first.append(await self.replay(s['replay']))
        # the job's core tools as functions; every other Dan tool and skill through the catalog (dan_tools)
        from app.services import dan_tools
        mcp = await list_tools()
        native = job_tools(mcp)
        instructions = (s.get('instructions') or '') + chr(10) + dan_tools.catalog(mcp, native=[t['name'] for t in native])
        provider.start(instructions, native + [dan_tools.HELP, dan_tools.USE], first)
        totals = {'input': 0, 'cached': 0, 'output': 0, 'cache_write': 0, 'steps': 0, 'model': model}
        for turn in range(MAX_TURNS):
            if self.read().get('state') == 'cancelled': return
            started = time.monotonic()
            step = await provider.step()
            u = step['usage']
            for k in ('input', 'cached', 'output', 'cache_write'): totals[k] += u.get(k, 0) or 0
            totals['steps'] += 1
            self.state.change(self.job_id, lambda st: st.update(usage=dict(totals)))
            self.state.publish(self.job_id, 'diagnostic', f"model {time.monotonic()-started:.1f}s in={u['input']} cached={u['cached']} out={u['output']}")
            calls, text = step['calls'], step['text']
            if text and calls:
                self.state.publish(self.job_id, 'progress', text[:3000])
            results = []
            for call in calls:
                if self.read().get('state') == 'cancelled': return
                called = time.monotonic()
                try:
                    if call['name'] == 'dan_tool_help':
                        contents = [type('T', (), {'type': 'text', 'text': dan_tools.help_text(mcp, str(call['args'].get('name') or ''))})()]
                    elif call['name'] == 'dan_tool':
                        contents = await call_tool(str(call['args'].get('name') or ''), call['args'].get('arguments') or {})
                    else:
                        contents = await call_tool(call['name'], call['args'])
                except Exception as exc:
                    contents = [type('T', (), {'type': 'text', 'text': f'操作は実行していません: {type(exc).__name__}: {str(exc)[:300]}'})()]
                output, images = function_output(contents)
                trace_step(call, output, images, time.monotonic() - called)
                results.append({'id': call['id'], 'output': output, 'images': images})
            if results: provider.tool_results(results)
            extras = self.new_inputs()
            for extra in extras:
                provider.user('追加の指示: ' + extra['text'])
            if calls or extras:
                continue
            # the model ended its turn with words only
            s = self.read()
            if s['state'] in ('awaiting_confirmation', 'paused') or s.get('approved') or s['revision'] > s['applied_revision']:
                while s['state'] in ('awaiting_confirmation', 'paused'):
                    await asyncio.sleep(.2); s = self.read()
                if s['state'] == 'cancelled' or s['state'] in self.state.TERMINAL: return
                continuation = {'state': s['state'], 'confirmation': s.get('confirmation'), 'approved': bool(s.get('approved')),
                                'new_inputs': [i for i in s['inputs'] if i['revision'] > s['applied_revision']]}
                top = max([i['revision'] for i in continuation['new_inputs']] + [s['applied_revision']])
                self.state.change(self.job_id, lambda st: st.update(applied_revision=max(st['applied_revision'], top)))
                provider.user(CONTINUATION + json.dumps(continuation, ensure_ascii=False))
                continue
            if not text: raise RuntimeError('作業結果が空でした')
            self.state.publish(self.job_id, 'result', text, result=text, state='completed')
            return
        raise RuntimeError('作業の手数が上限に達しました')


def main():
    job_id = sys.argv[1]
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from app.mcp_server import _ensure_env_from_dotenv
    _ensure_env_from_dotenv()
    # The model choice and the providers' keys are read from .env at every job: switching the job model is an .env edit,
    # with no restart of the Core that spawns this worker.
    from dotenv import dotenv_values
    fresh = dotenv_values(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))
    for key in ('DAN_API_JOB_MODEL', 'DAN_API_JOB_REASONING', 'DAN_API_JOB_TOOLS', 'DEEPSEEK_API_KEY', 'ANTHROPIC_API_KEY', 'DAN_CHAT_BASE_URL', 'DAN_CHAT_API_KEY'):
        if fresh.get(key): os.environ[key] = fresh[key]
    from app.services import command_job_state as state
    worker = Worker(job_id)
    try:
        asyncio.run(worker.run())
    except Exception as exc:
        saved = state.read(job_id)
        if saved and saved['state'] not in state.TERMINAL:
            text = '作業を停止しました: ' + str(exc)[:600]
            state.publish(job_id, 'error', text, state='failed', error=text)
        raise


if __name__ == '__main__':
    main()
