"""Subscription exhaustion is a handoff, never a successful final answer.

Try each provider at most once per request. Keep the user's selected model;
short cooldowns avoid sending every room to an account that just rejected us.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any

_lock = threading.Lock()
_blocked: dict[str, float] = {}
_LIMIT = re.compile(
    r"(?:you(?:'ve| have) (?:hit|reached) your (?:weekly |usage |5.hour )?limit|"
    r"weekly limit (?:reached|exceeded)|usage limit (?:reached|exceeded)|"
    r"rate[_ -]?limit(?:[_ -]exceeded| reached)|insufficient_quota|"
    r"契約利用枠に達|利用上限に達)", re.I)


def exhausted(event: dict[str, Any]) -> bool:
    if event.get('quota_exhausted'):
        return True
    # A successful answer discussing limits is not a provider rejection.
    text = str(event.get('result_text') or event.get('result') or event.get('text') or '')
    errors = str(event.get('errors') or event.get('error') or event.get('message') or '')
    rejected = event.get('is_error') or event.get('type') == 'error'
    bare_notice = bool(re.match(r"^you(?:'ve| have) (?:hit|reached) your .*limit", text.strip(), re.I))
    return bool((rejected or bare_notice) and _LIMIT.search(text + ' ' + errors))


def mark_exhausted(backend: str) -> None:
    with _lock:
        _blocked[backend] = time.time() + 300


def available(backend: str) -> bool:
    with _lock:
        return _blocked.get(backend, 0) <= time.time()


def alternative(backend: str) -> str:
    from app.agent import model_catalog
    if backend == 'codex':
        return 'opus'
    choices = model_catalog.codex_options()
    return next((o['id'] for o in choices if o['id'].endswith('-sol')),
                choices[0]['id'] if choices else 'gpt-6-astra')


def preferred(model: str) -> str:
    from app.agent.codex_runner import backend_for_model
    backend = backend_for_model(model)
    other = alternative(backend)
    return other if not available(backend) and available(backend_for_model(other)) else model


def partial_text(result: dict) -> str:
    return '\n\n'.join(t for t in result.get('final_text_parts', [])
                       if t.strip() and not exhausted({'text': t, 'is_error': True}))


def handoff_content(content: str, partial: str) -> str:
    return (content + '\n\n<provider_handoff>\n'
            '前の担当は利用上限で中断しました。同じ依頼を引き継いで続けてください。'
            '会話の記録・実行記録・ファイルを先に確認し、完了済みの送信・購入・編集を重複実行しないこと。'
            '\n直前までの経過:\n' + partial[-16000:] + '\n</provider_handoff>')
