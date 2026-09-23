"""The model side of an API job, for three kinds of API: OpenAI Responses (gpt-*), Anthropic Messages (claude-*) and
OpenAI-compatible Chat Completions (deepseek-* and other open-model providers). Each keeps its own conversation and
answers one question: given what came back from the tools, what does the model do next?

    provider.start(instructions, tools, first_messages)
    turn = await provider.step()                 # {'text', 'calls': [{'id','name','args'}], 'usage': {...}}
    provider.tool_results([{'id','output','images'}]); provider.user(text)

Usage is reported per step as input / cached input / output tokens, so a job's cost can be computed afterwards with the
provider's own prices (the model comparison of 2026-09-23 needs it).
"""
import asyncio
import json
import os


def kind_of(model):
    if model.startswith('claude'): return 'anthropic'
    if model.startswith(('gpt-', 'o')): return 'openai'
    return 'chat'


def make(model):
    return {'anthropic': Anthropic, 'openai': OpenAIResponses, 'chat': ChatCompletions}[kind_of(model)](model)


class OpenAIResponses:
    def __init__(self, model):
        from openai import OpenAI
        from app.config import settings
        self.model, self.client = model, OpenAI(api_key=settings.OPENAI_API_KEY, timeout=600)
        self.previous, self.pending = None, []

    def start(self, instructions, tools, messages):
        self.instructions = instructions
        self.tools = [{'type': 'web_search'}] + [{'type': 'function', 'name': t['name'], 'description': t['description'], 'parameters': t['parameters']} for t in tools]
        self.pending = [{'role': 'user', 'content': m} for m in messages]

    def tool_results(self, results):
        for r in results:
            self.pending.append({'type': 'function_call_output', 'call_id': r['id'], 'output': r['output']})
        images = [i for r in results for i in (r.get('images') or [])[:2]]
        if images:
            self.pending.append({'role': 'user', 'content': [{'type': 'input_image', 'image_url': i} for i in images[:2]]})

    def user(self, text):
        self.pending.append({'role': 'user', 'content': text})

    async def step(self):
        kwargs = {'model': self.model, 'instructions': self.instructions, 'input': self.pending, 'tools': self.tools, 'tool_choice': 'auto',
                  'parallel_tool_calls': False, 'reasoning': {'effort': os.environ.get('DAN_API_JOB_REASONING', 'low')}, 'store': True}
        if self.previous: kwargs['previous_response_id'] = self.previous
        r = await asyncio.to_thread(self.client.responses.create, **kwargs)
        self.previous, self.pending = r.id, []
        calls = [{'id': o.call_id, 'name': o.name, 'args': _args(o.arguments)} for o in r.output if getattr(o, 'type', '') == 'function_call']
        text = '\n'.join(''.join(getattr(c, 'text', '') for c in (o.content or [])) for o in r.output if getattr(o, 'type', '') == 'message').strip()
        u = r.usage
        cached = getattr(getattr(u, 'input_tokens_details', None), 'cached_tokens', 0) or 0
        return {'text': text, 'calls': calls, 'usage': {'input': u.input_tokens - cached, 'cached': cached, 'output': u.output_tokens}}


class Anthropic:
    def __init__(self, model):
        import anthropic
        self.model, self.client = model, anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'), timeout=600)
        self.messages, self.pending = [], []

    def start(self, instructions, tools, messages):
        self.system = [{'type': 'text', 'text': instructions, 'cache_control': {'type': 'ephemeral'}}]
        self.tools = [{'name': t['name'], 'description': t['description'], 'input_schema': t['parameters']} for t in tools]
        if self.tools: self.tools[-1]['cache_control'] = {'type': 'ephemeral'}
        self.pending = [{'type': 'text', 'text': m} for m in messages]

    def tool_results(self, results):
        for r in results:
            content = [{'type': 'text', 'text': r['output']}]
            for i in (r.get('images') or [])[:2]:
                media, data = i.split(';base64,', 1)
                content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': media.replace('data:', ''), 'data': data}})
            self.pending.append({'type': 'tool_result', 'tool_use_id': r['id'], 'content': content})

    def user(self, text):
        self.pending.append({'type': 'text', 'text': text})

    async def step(self):
        # The newest user turn carries a cache breakpoint: the whole conversation before it is read from the cache next step
        for m in self.messages:
            for block in m['content'] if isinstance(m['content'], list) else []:
                block.pop('cache_control', None)
        turn = [dict(b) for b in self.pending]
        turn[-1]['cache_control'] = {'type': 'ephemeral'}
        self.messages.append({'role': 'user', 'content': turn})
        self.pending = []
        r = await asyncio.to_thread(self.client.messages.create, model=self.model, max_tokens=4096, system=self.system,
                                    tools=self.tools + [{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 3}],
                                    messages=self.messages)
        self.messages.append({'role': 'assistant', 'content': [b.model_dump(exclude_none=True) for b in r.content]})
        calls = [{'id': b.id, 'name': b.name, 'args': b.input or {}} for b in r.content if b.type == 'tool_use']
        text = '\n'.join(b.text for b in r.content if b.type == 'text').strip()
        u = r.usage
        return {'text': text, 'calls': calls, 'usage': {'input': (u.input_tokens or 0) + (getattr(u, 'cache_creation_input_tokens', 0) or 0),
                                                        'cached': getattr(u, 'cache_read_input_tokens', 0) or 0, 'output': u.output_tokens,
                                                        'cache_write': getattr(u, 'cache_creation_input_tokens', 0) or 0}}


class ChatCompletions:
    """OpenAI-compatible chat completions: DeepSeek (api.deepseek.com) by default; DAN_CHAT_BASE_URL/DAN_CHAT_API_KEY for others."""
    def __init__(self, model):
        from openai import OpenAI
        base = os.environ.get('DAN_CHAT_BASE_URL') or ('https://api.deepseek.com' if model.startswith('deepseek') else '')
        key = os.environ.get('DAN_CHAT_API_KEY') or os.environ.get('DEEPSEEK_API_KEY')
        self.model, self.client = model, OpenAI(api_key=key, base_url=base, timeout=600)
        self.messages = []

    def start(self, instructions, tools, messages):
        self.messages = [{'role': 'system', 'content': instructions}] + [{'role': 'user', 'content': m} for m in messages]
        self.tools = [{'type': 'function', 'function': {'name': t['name'], 'description': t['description'], 'parameters': t['parameters']}} for t in tools]

    def tool_results(self, results):
        # every tool message first (the API wants them right after the assistant's tool_calls), then any images
        for r in results:
            self.messages.append({'role': 'tool', 'tool_call_id': r['id'], 'content': r['output']})
        images = [i for r in results for i in (r.get('images') or [])[:2]]
        if images:
            self.messages.append({'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': i}} for i in images[:2]]})

    def user(self, text):
        self.messages.append({'role': 'user', 'content': text})

    async def step(self):
        r = await asyncio.to_thread(self.client.chat.completions.create, model=self.model, messages=self.messages, tools=self.tools, tool_choice='auto')
        m = r.choices[0].message
        entry = {'role': 'assistant', 'content': m.content or ''}
        if m.tool_calls: entry['tool_calls'] = [tc.model_dump(exclude_none=True) for tc in m.tool_calls]
        if getattr(m, 'reasoning_content', None) is not None: entry['reasoning_content'] = m.reasoning_content
        self.messages.append(entry)
        calls = [{'id': tc.id, 'name': tc.function.name, 'args': _args(tc.function.arguments)} for tc in (m.tool_calls or [])]
        u = r.usage
        cached = getattr(u, 'prompt_cache_hit_tokens', None)
        if cached is None: cached = getattr(getattr(u, 'prompt_tokens_details', None), 'cached_tokens', 0) or 0
        return {'text': (m.content or '').strip(), 'calls': calls, 'usage': {'input': u.prompt_tokens - cached, 'cached': cached, 'output': u.completion_tokens}}


def _args(raw):
    try: return json.loads(raw or '{}')
    except ValueError: return {}
