"""Bounded, typed decisions. No tool authority, generated strings, or retries."""
from __future__ import annotations

import asyncio
import json
import math
import os
import time

import httpx
from app.services import jev_browser_budget as budget

from app.tools.browser_metrics import record_timing

_credential_cache = {}  # Per-user, process memory only; never persisted.


def choice_answers(data, questions):
    """Reject malformed/partial distributions rather than trusting a label alone."""
    answers = data.get('answers')
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ValueError('answer_set')
    for name, question in questions.items():
        answer = answers[name]
        options = question['criteria']
        if not isinstance(answer, dict) or answer.get('type') != 'choice':
            raise ValueError('answer_type')
        probs = answer.get('probabilities')
        if not isinstance(probs, dict) or set(probs) != set(options):
            raise ValueError('distribution_keys')
        if any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in probs.values()):
            raise ValueError('distribution_values')
        confidence = answer.get('confidence')
        if type(confidence) not in (float, int) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError('confidence')
        selected = answer.get('choice')
        if selected not in options or abs(sum(probs.values()) - 1) > .01:
            raise ValueError('choice')
        if probs[selected] + 1e-6 < max(probs.values()):
            raise ValueError('choice_not_maximum')
    return answers


class Decisions:
    """One authenticated keepalive connection pool for a bounded workflow.

    The existing credential service owns secrets. Use the evaluation credential
    name first, then the older editor name; do not copy or log either value.
    """
    def __init__(self, user_id, *, timeout=1.2, max_calls=12, enabled=None):
        self.user_id = user_id
        self.timeout = timeout
        self.max_calls = max_calls
        self.calls = 0
        self._key = None
        self._client = None
        self.unavailable = False
        self.enabled = budget.enabled() if enabled is None else enabled

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()
        self._key = None

    async def _credential(self):
        if self._key:
            return self._key
        if not self.user_id:
            return None
        cached = _credential_cache.get(self.user_id)
        if cached and time.monotonic() < cached[0]:
            self._key = cached[1]
            return self._key
        from app.services.credentials_service import get_credentials_service
        def read():
            async def lookup():
                service = get_credentials_service()
                for name in ('typesafe', 'typesafe_jev'):
                    value = await service.get_credential(self.user_id, name)
                    if value and value.get('credential_type') == 'api_key' and value.get('password'):
                        return value['password']
            return asyncio.run(lookup())
        self._key = await asyncio.to_thread(read)
        if len(_credential_cache) >= 128:
            _credential_cache.pop(next(iter(_credential_cache)))
        _credential_cache[self.user_id] = (time.monotonic() + (30 if self._key else 5), self._key)
        return self._key

    async def choose(self, state, questions):
        if not self.enabled:
            return {'available': False, 'reason': 'disabled', 'elapsed_ms': 0}
        if self.unavailable or self.calls >= self.max_calls:
            return {'available': False, 'reason': 'decision_budget', 'elapsed_ms': 0}
        # A conservative byte bound, not an estimate that Japanese bytes=tokens.
        body = {'model': 'jev-latest', 'state': state, 'questions': questions}
        if len(json.dumps(body, ensure_ascii=False).encode('utf-8')) > 24000:
            return {'available': False, 'reason': 'state_too_large', 'elapsed_ms': 0}
        if not questions or any(q.get('type') != 'choice' or not 2 <= len(q.get('criteria', {})) <= 255 for q in questions.values()):
            return {'available': False, 'reason': 'invalid_questions', 'elapsed_ms': 0}
        started = time.perf_counter()
        async def request():
            key = await self._credential()
            if not key:
                return {'available': False, 'reason': 'not_configured'}
            if not await asyncio.to_thread(budget.reserve,body,self.user_id):
                return {'available':False,'reason':'approved_budget_unavailable'}
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=self.timeout)
            self.calls += 1
            response = await self._client.post('https://api.typesafe.ai/v1/systemone',
                headers={'Authorization': 'Bearer ' + key}, json=body)
            if response.status_code in (401,403):
                _credential_cache.pop(self.user_id, None)
            response.raise_for_status()
            data = response.json()
            answers = choice_answers(data, questions)
            return {'available': True, 'answers': answers, 'model': data.get('model'), 'usage': data.get('usage', {})}
        try:
            result = await asyncio.wait_for(request(), timeout=self.timeout)
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError, TypeError):
            # Error bodies can echo inputs. Only the category leaves this layer.
            result = {'available': False, 'reason': 'unavailable'}
        if not result['available']:
            self.unavailable = True
        result['elapsed_ms'] = round((time.perf_counter()-started)*1000, 2)
        record_timing('decision', 'jev', result['elapsed_ms'], 'ok' if result['available'] else result['reason'])
        return result
