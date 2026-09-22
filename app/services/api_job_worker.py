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
MODEL = lambda: os.environ.get('DAN_API_JOB_MODEL', 'gpt-6-astra')   # gpt-6-astra: the CLI's model; gpt-5.6 flailed on tool arguments (2026-09-23 15:14)
REASONING = lambda: os.environ.get('DAN_API_JOB_REASONING', 'low')
MAX_TURNS = 120
# The tools a job needs. The MCP list carries 33 tools (56k characters of schema) for the CLI; sending all of them on every
# call made a step 6-8s (2026-09-23 15:11). DAN_API_JOB_TOOLS=all sends the whole list.
JOB_TOOLS = lambda: os.environ.get('DAN_API_JOB_TOOLS', 'browser,browser_script,flow,desktop,lookup,get_credentials,save_credentials,get_personal_info,'
                                   'get_location,read_url,bash,read_file,write_file,wait_until,job_confirmation,job_progress,command_center').split(',')
OUTPUT_CHARS = 12000
CONTINUATION = ('本人の返事を受け付けた現在の作業状態です。確定操作はまだ実行していません。画面を読み取り、承認済みの具体的な操作だけを再開してください。'
                '条件変更があれば以前の承認は無効です。\n')


def openai_tools(mcp_tools):
    """The MCP tool list as Responses API function tools."""
    out = [{'type': 'web_search'}]
    for tool in mcp_tools:
        if JOB_TOOLS() != ['all'] and tool.name not in JOB_TOOLS(): continue
        schema = dict(tool.inputSchema or {'type': 'object', 'properties': {}})
        out.append({'type': 'function', 'name': tool.name, 'description': (tool.description or '')[:1024], 'parameters': schema})
    return out


def function_output(contents):
    """What the model reads back: the texts joined (capped); images are returned separately as an input_image message."""
    texts, images = [], []
    for c in contents:
        if getattr(c, 'type', '') == 'text': texts.append(c.text)
        elif getattr(c, 'type', '') == 'image': images.append({'type': 'input_image', 'image_url': f'data:{c.mimeType};base64,{c.data}'})
    return '\n'.join(texts)[:OUTPUT_CHARS] or '（出力なし）', images


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

    async def call_model(self, items, instructions, tools, previous):
        from openai import OpenAI
        from app.config import settings
        if self.client is None: self.client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=600)
        kwargs = {'model': MODEL(), 'instructions': instructions, 'input': items, 'tools': tools, 'tool_choice': 'auto',
                  'parallel_tool_calls': False, 'reasoning': {'effort': REASONING()}, 'store': True}
        if previous: kwargs['previous_response_id'] = previous
        return await asyncio.to_thread(self.client.responses.create, **kwargs)

    async def run(self):
        from app.mcp_server import list_tools, call_tool
        s = self.read()
        instructions = s.get('instructions') or ''
        tools = openai_tools(await list_tools())
        items = [{'role': 'user', 'content': m} for m in s.get('history', [])] + [{'role': 'user', 'content': s['task']}]
        previous, result = None, ''
        for turn in range(MAX_TURNS):
            if self.read().get('state') == 'cancelled': return
            started = time.monotonic()
            response = await self.call_model(items, instructions, tools, previous)
            previous = response.id
            usage = getattr(response, 'usage', None)
            self.state.publish(self.job_id, 'diagnostic', f'model {time.monotonic()-started:.1f}s'+(f' in={usage.input_tokens} out={usage.output_tokens}' if usage else ''))
            items = []
            calls = [o for o in response.output if getattr(o, 'type', '') == 'function_call']
            texts = [''.join(getattr(c, 'text', '') for c in (o.content or [])) for o in response.output if getattr(o, 'type', '') == 'message']
            text = '\n'.join(t for t in texts if t).strip()
            if text and calls:
                self.state.publish(self.job_id, 'progress', text[:3000])
            for call in calls:
                if self.read().get('state') == 'cancelled': return
                try: args = json.loads(call.arguments or '{}')
                except ValueError: args = {}
                try: contents = await call_tool(call.name, args)
                except Exception as exc:
                    contents = [type('T', (), {'type': 'text', 'text': f'操作は実行していません: {type(exc).__name__}: {str(exc)[:300]}'})()]
                output, images = function_output(contents)
                items.append({'type': 'function_call_output', 'call_id': call.call_id, 'output': output})
                if images: items.append({'role': 'user', 'content': images[:2]})
            for extra in self.new_inputs():
                items.append({'role': 'user', 'content': '追加の指示: ' + extra['text']})
            if calls or (items and not calls):
                continue
            # the model ended its turn with words only
            result = text
            s = self.read()
            if s['state'] in ('awaiting_confirmation', 'paused') or s.get('approved') or s['revision'] > s['applied_revision']:
                while s['state'] in ('awaiting_confirmation', 'paused'):
                    await asyncio.sleep(.2); s = self.read()
                if s['state'] == 'cancelled' or s['state'] in self.state.TERMINAL: return
                continuation = {'state': s['state'], 'confirmation': s.get('confirmation'), 'approved': bool(s.get('approved')),
                                'new_inputs': [i for i in s['inputs'] if i['revision'] > s['applied_revision']]}
                top = max([i['revision'] for i in continuation['new_inputs']] + [s['applied_revision']])
                self.state.change(self.job_id, lambda st: st.update(applied_revision=max(st['applied_revision'], top)))
                items = [{'role': 'user', 'content': CONTINUATION + json.dumps(continuation, ensure_ascii=False)}]
                continue
            if not result: raise RuntimeError('作業結果が空でした')
            self.state.publish(self.job_id, 'result', result, result=result, state='completed')
            return
        raise RuntimeError('作業の手数が上限に達しました')


def main():
    job_id = sys.argv[1]
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from app.mcp_server import _ensure_env_from_dotenv
    _ensure_env_from_dotenv()
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
