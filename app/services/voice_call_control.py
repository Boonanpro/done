"""Fast, bounded call intent review. This layer never executes tools or ends calls."""
import asyncio
import time
from app.services.jev_decisions import Decisions


QUESTIONS = {
    'call': {
        'type': 'choice',
        'instructions': 'Determine the latest user utterance intent in this ongoing voice call. Use preceding dialogue only as context. Ending a task, stopping an explanation, quoted speech, past failures, and another telephone call are not requests to disconnect this call. Do not infer consent from an assistant farewell. Recognition ambiguity requires review.',
        'criteria': {
            'end': 'The user now requests ending this voice call.',
            'keep': 'The user is not asking to end this voice call.',
            'review': 'Uncertain whether the user wants this voice call ended.',
        },
    },
    'intent': {
        'type': 'choice',
        'instructions': 'Does the latest user utterance express a current, affirmative request to disconnect this conversation? Assess the whole utterance including corrections and negations; quotations, hypothetical examples and reports of earlier events are not current requests.',
        'criteria': {
            'request': 'An affirmative current request to disconnect this conversation.',
            'other': 'A report, question, quotation, negation, correction to keep talking, or unrelated request.',
            'uncertain': 'Insufficient or ambiguous evidence for a current disconnect request.',
        },
    },
}


def decision(result):
    """Two related judgments are NOT independent evidence or a correctness guarantee.

    Conservative abstention; probability concentration is not measured accuracy.
    The client must still verify silence and discard stale results.
    """
    if not result.get('available'):
        return 'review'
    answers = result['answers']
    for name, expected in (('call', 'end'), ('intent', 'request')):
        answer = answers[name]
        if answer['choice'] != expected or min(answer['confidence'], answer['probabilities'][expected]) < .95:
            return 'review'
    return 'end'


class CallControl:
    """One credential and HTTP pool per call, prepared during Live connection.

    No model request is made merely by opening a call. A new utterance can recover
    from a previous unavailable decision; an uncertain request is never replayed.
    """
    def __init__(self, user_id):
        self.user_id = user_id
        self.client = None
        self.preparing = None
        self.closed = False

    def warm(self):
        if self.closed or self.preparing:
            return
        self.preparing = asyncio.create_task(self._prepare())

    async def _prepare(self):
        self.client = Decisions(self.user_id, timeout=.9, max_calls=256)
        await self.client.__aenter__()
        try:
            await asyncio.wait_for(self.client._credential(), .9)
        except Exception:
            pass  # A later new utterance may obtain the credential.

    async def choose(self, state):
        if self.closed:
            return {'available': False, 'elapsed_ms': 0}
        self.warm()
        try:
            await asyncio.shield(self.preparing)
        except asyncio.CancelledError:
            if self.closed:
                return {'available': False, 'elapsed_ms': 0}
            raise
        if self.closed:
            return {'available': False, 'elapsed_ms': 0}
        self.client.unavailable = False
        return await self.client.choose(state, QUESTIONS)

    def close(self):
        self.closed = True
        if self.preparing and not self.preparing.done():
            self.preparing.cancel()
        if self.client:
            client, self.client = self.client, None
            asyncio.create_task(client.__aexit__(None, None, None))


async def review(user_id, dialogue, control=None):
    # The latest user utterance is explicit, rather than hidden behind a later
    # assistant farewell. Retain only bounded relevant conversational context.
    latest = next((i for i in range(len(dialogue)-1, -1, -1) if dialogue[i]['role'] == 'user'), None)
    if latest is None:
        return {'action': 'review', 'reason': 'no_user_utterance'}
    state = {'call_state': 'connected', 'recent_dialogue': dialogue[max(0, latest-7):latest],
             'latest_user': dialogue[latest]['text']}
    if control is None:
        async with Decisions(user_id, timeout=.9, max_calls=1) as client:
            result = await client.choose(state, QUESTIONS)
    else:
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(control.choose(state), .9)
        except (asyncio.TimeoutError, ValueError, RuntimeError):
            result = {'available': False, 'elapsed_ms': round((time.perf_counter()-started)*1000, 2)}
    return {'action': decision(result), 'elapsed_ms': result['elapsed_ms'],
            'available': result['available'], 'model': result.get('model')}
