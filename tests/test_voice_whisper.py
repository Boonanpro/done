"""A whisper the speech model does not take as speech reaches it as the owner's words (app/services/voice_whisper.py).

The audio here is made up: a whisper is breath noise shaped like speech (no pitch), an ordinary voice has a pitch. The
owner's own recordings (2026-09-24〜30) are run with scripts/check_voice_whisper.py and are not kept in the repository.
"""
import asyncio
import base64
import json
import time
from types import SimpleNamespace

import numpy as np
import pytest

from app.services import voice_whisper as W

RATE = W.RATE
rng = np.random.default_rng(7)


@pytest.fixture(autouse=True)
def no_transcriber_process(monkeypatch):
    monkeypatch.setattr(W, 'warm', lambda: None)


def floor(seconds, db=-62):
    return (rng.standard_normal(int(RATE * seconds)) * 10 ** (db / 20)).astype(np.float32)


def whisper(seconds, db=-30):
    """Breath noise in the 1〜5 kHz band, coming and going like syllables."""
    n = int(RATE * seconds)
    spectrum = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    spectrum[(freqs < 1000) | (freqs > 5000)] = 0
    x = np.fft.irfft(spectrum, n)
    x *= 0.6 + 0.4 * np.sin(2 * np.pi * 4 * np.arange(n) / RATE)
    x = x / np.sqrt((x * x).mean()) * 10 ** (db / 20)
    return (x + floor(seconds)).astype(np.float32)


def voice(seconds, db=-30, f0=140):
    t = np.arange(int(RATE * seconds)) / RATE
    x = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 20))
    x = x / np.sqrt((x * x).mean()) * 10 ** (db / 20)
    return (x + floor(seconds)).astype(np.float32)


def chunks(audio, size=4800):
    pcm = (np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes()
    return [base64.b64encode(pcm[i:i + size * 2]).decode() for i in range(0, len(pcm), size * 2)]


class Clock:
    def __init__(self): self.t = 100.0
    def __call__(self): return self.t


async def feed(listener, clock, audio):
    for part in chunks(audio):
        clock.t += 0.2
        listener.audio(part)
        await asyncio.sleep(0)


async def settle(listener):
    while listener.tasks:
        await asyncio.gather(*list(listener.tasks), return_exceptions=True)


def test_the_ear_cuts_a_whisper_and_a_voice_and_tells_them_apart():
    clock = Clock()
    ear = W.Ear(clock)
    for part in chunks(np.concatenate([floor(2), whisper(1.2), floor(1.2), voice(1.2), floor(1.2)])):
        clock.t += 0.2
        ear.audio(part)
    cut = ear.take()
    assert len(cut) == 2
    assert cut[0][3] <= W.MAX_VOICED < cut[1][3]
    assert 0.8 <= cut[0][4] <= 1.4          # speech seconds of the whisper
    assert cut[0][1] < cut[0][2] < cut[1][1]  # in time order


@pytest.mark.asyncio
async def test_a_whisper_reaches_the_speech_model_as_the_owners_words(monkeypatch):
    monkeypatch.setattr(W, 'ANSWER_WAIT_S', 0)
    sent, log, heard_words, asked = [], [], [], []
    async def send(event): sent.append(event)
    dialogue = SimpleNamespace(turns=[], add=lambda role, text: dialogue.turns.append((role, text)))
    def transcriber(audio):
        asked.append(len(audio) / RATE)
        return '明日って何曜日？'
    clock = Clock()
    listener = W.Listener(send, lambda phase, **f: log.append((phase, f)), dialogue, {}, clock=clock, transcriber=transcriber,
                          on_words=heard_words.append)
    await feed(listener, clock, np.concatenate([floor(2), whisper(1.5), floor(1.4)]))
    await settle(listener)
    assert len(asked) == 1 and 1.5 <= asked[0] <= 2.5
    # handed over with the commentary Dan speaks after: on 11/8 22:20 the instructions alone were left unanswered, and
    # response.create is refused in this call (client delegation)
    assert [e['type'] for e in sent] == ['session.instructions.append', 'session.commentary.append']
    assert sent[0]['delegation_id'] is None and '「明日って何曜日？」' in sent[0]['content']
    assert sent[1]['delegation_id'] is None and '「明日って何曜日？」' in sent[1]['content']
    assert all(e['event_id'].startswith('dan-whisper-') for e in sent)   # an error about them is not a failure of the work
    assert dialogue.turns == [('user', '明日って何曜日？')] and heard_words == ['明日って何曜日？']
    assert [p for p, _ in log] == ['whisper_heard', 'whisper_unanswered']
    assert log[0][1].get('read_ahead') is True      # read at 0.3 s of quiet: nothing was said after it


@pytest.mark.asyncio
async def test_a_whisper_that_goes_on_after_a_short_pause_is_read_whole(monkeypatch):
    monkeypatch.setattr(W, 'ANSWER_WAIT_S', 0)
    sent, log, asked = [], [], []
    async def send(event): sent.append(event)
    def transcriber(audio):
        asked.append(round(len(audio) / RATE, 1))
        return '前半' if len(asked) == 1 else '前半と後半'
    clock = Clock()
    listener = W.Listener(send, lambda phase, **f: log.append((phase, f)), clock=clock, transcriber=transcriber)
    # 0.4 s between the two halves: past the read-ahead (0.3 s), short of the end (0.6 s)
    await feed(listener, clock, np.concatenate([floor(2), whisper(1.2), floor(0.4), whisper(1.2), floor(1.4)]))
    await settle(listener)
    assert len(asked) >= 2 and asked[-1] > asked[0] + 1.0
    given = [e['content'] for e in sent if e['type'] == 'session.instructions.append']
    assert len(given) == 1 and '「前半と後半」' in given[0]


@pytest.mark.asyncio
async def test_dan_is_told_when_a_whisper_could_not_be_made_out_but_not_over_and_over(monkeypatch):
    monkeypatch.setattr(W, 'ANSWER_WAIT_S', 0)
    sent, log = [], []
    async def send(event): sent.append(event)
    clock = Clock()
    listener = W.Listener(send, lambda phase, **f: log.append((phase, f)), clock=clock, transcriber=lambda a: ('', 'unsure'))
    await feed(listener, clock, np.concatenate([floor(2), whisper(1.2), floor(1.4), whisper(1.2), floor(1.4)]))
    await settle(listener)
    spoken = [e for e in sent if e['type'] == 'session.commentary.append']
    assert len(spoken) == 1 and '聞き取れなかった' in spoken[0]['content']
    assert [p for p, _ in log].count('whisper_unheard') == 1
    # breath or Whisper's inventions on quiet audio are not 「something was said」
    sent.clear()
    quiet = W.Listener(send, lambda *a, **k: None, clock=clock, transcriber=lambda a: ('', 'silent'))
    await feed(quiet, clock, np.concatenate([floor(2), whisper(1.2), floor(1.4)]))
    await settle(quiet)
    assert sent == []


@pytest.mark.asyncio
async def test_what_the_owner_whispers_after_dan_finished_is_kept(monkeypatch):
    monkeypatch.setattr(W, 'ANSWER_WAIT_S', 0)
    sent, log, asked = [], [], []
    async def send(event): sent.append(event)
    clock = Clock()
    listener = W.Listener(send, lambda phase, **f: log.append((phase, f)), clock=clock,
                          transcriber=lambda a: asked.append(len(a) / RATE) or 'それで、明日は？')
    await feed(listener, clock, floor(2))
    loud = (np.sin(np.arange(RATE // 2) / RATE * 2 * np.pi * 200) * 0.3 * 32767).astype('<i2').tobytes()
    listener.dan_audio(base64.b64encode(loud).decode())   # Dan's last half second
    await feed(listener, clock, np.concatenate([whisper(3.0), floor(1.4)]))   # the owner from the same moment, on for 3 s
    await settle(listener)
    assert len(asked) == 1 and 1.0 <= asked[0] <= 2.3       # read from a second after Dan's voice ended
    heard = [f for p, f in log if p == 'whisper_heard']
    assert heard and heard[0].get('trimmed') is True


@pytest.mark.asyncio
async def test_how_long_dan_took_to_answer_is_recorded():
    sent, log, spoke = [], [], {}
    clock = Clock()
    async def send(event):
        sent.append(event)
        if event['type'] == 'session.commentary.append':
            spoke['dan_words'] = clock.t + 0.7    # Dan's first words, 0.7 s after the words were given
    listener = W.Listener(send, lambda phase, **f: log.append((phase, f)), None, spoke, clock=clock, transcriber=lambda a: 'はい')
    await feed(listener, clock, np.concatenate([floor(2), whisper(1.5), floor(1.4)]))
    await settle(listener)
    answered = [f for p, f in log if p == 'whisper_answered']
    assert answered and answered[0]['whisper_reply_ms'] == 700 and answered[0]['from_end_ms'] > 700


@pytest.mark.asyncio
async def test_an_ordinary_voice_is_left_to_the_speech_model():
    sent, asked = [], []
    async def send(event): sent.append(event)
    clock = Clock()
    listener = W.Listener(send, lambda *a, **k: None, clock=clock, transcriber=lambda a: asked.append(a) or 'x')
    await feed(listener, clock, np.concatenate([floor(2), voice(1.5), floor(1.4)]))
    await settle(listener)
    assert asked == [] and sent == []


@pytest.mark.asyncio
async def test_what_the_speech_model_heard_itself_is_not_given_twice():
    sent, log = [], []
    async def send(event): sent.append(event)
    clock = Clock()
    listener = W.Listener(send, lambda phase, **f: log.append((phase, f)), clock=clock, transcriber=lambda a: '電話切って')
    await feed(listener, clock, floor(2))
    for part in chunks(whisper(1.5)):
        clock.t += 0.2
        listener.audio(part)
        listener.heard()            # Live's own transcript of the owner arrives meanwhile
    await feed(listener, clock, floor(1.4))
    await settle(listener)
    assert sent == [] and ('whisper_skipped', 'live_heard') in [(p, f.get('why')) for p, f in log]


@pytest.mark.asyncio
async def test_dans_own_voice_coming_back_through_the_earbuds_is_not_the_owner():
    sent, asked = [], []
    async def send(event): sent.append(event)
    clock = Clock()
    listener = W.Listener(send, lambda *a, **k: None, clock=clock, transcriber=lambda a: asked.append(a) or 'はい')
    await feed(listener, clock, floor(2))
    loud = (np.sin(np.arange(RATE) / RATE * 2 * np.pi * 200) * 0.3 * 32767).astype('<i2').tobytes()
    listener.dan_audio(base64.b64encode(loud).decode())   # one second of Dan, as the sideband sees it
    await feed(listener, clock, np.concatenate([whisper(1.2), floor(1.4)]))
    await settle(listener)
    assert asked == [] and sent == []


def test_what_whisper_invents_or_guesses_is_dropped(monkeypatch):
    monkeypatch.setattr(W, '_gpu', lambda: True)
    def segments(text, logprob=-0.2, ratio=1.0, no_speech=0.0):
        return [{'text': text, 'avg_logprob': logprob, 'compression_ratio': ratio, 'no_speech_prob': no_speech}]
    audio = whisper(1.0)
    for result, words in [(segments('ご視聴ありがとうございました'), ''), (segments('次は、次は、次は、次は'), ''),
                          (segments('おすすめの2つのめちゃい', logprob=-0.93), ''), (segments('明日何曜日?'), '明日何曜日?'),
                          (segments('電話切って', no_speech=0.9), '')]:
        monkeypatch.setattr(W, '_segments_gpu', lambda x, r=result: r)
        assert W.transcribe(audio) == words
    # why: what was not trusted is told apart, so an unsure reading can be answered with 「聞き取れなかった」
    for result, why in [(segments('ご視聴ありがとうございました'), 'silent'), (segments('おすすめの2つのめちゃい', logprob=-0.93), 'unsure'),
                        (segments('ご視聴ありがとうございました', logprob=-1.2), 'silent'), (segments('次は、次は、次は、次は'), 'loop')]:
        monkeypatch.setattr(W, '_segments_gpu', lambda x, r=result: r)
        assert W.reading(audio) == ('', why)
    # 「もしもしもしもし」 is how a call starts, not Whisper looping (2026-09 call: dropped as a loop)
    monkeypatch.setattr(W, '_segments_gpu', lambda x: segments('もしもしもしもしもしもしおい'))
    assert W.transcribe(audio) == 'もしもし、おい'


@pytest.mark.asyncio
async def test_an_error_about_a_handed_over_whisper_is_not_announced_as_a_failure_of_the_work():
    from app.services import voice_sideband as S
    sent, log = [], []
    async def send(event): sent.append(event)
    dialogue = SimpleNamespace(failure_notices=set())
    error = {'type': 'error', 'event_id': 'e1', 'error': {'type': 'invalid_request_error', 'code': 'invalid_request_error',
             'message': 'response.create requires a session with Responses delegation.', 'client_event_id': 'dan-whisper-reply-1'}}
    await S.report_backend_failure(send, error, dialogue, lambda phase, **f: log.append(phase))
    assert sent == [] and log == ['whisper_failed']


@pytest.mark.asyncio
async def test_the_calls_sideband_hands_a_whisper_to_the_speech_model(monkeypatch, tmp_path):
    """The real sideband loop with a fake Live socket: the call's input arrives as reflected audio only (no transcript of
    the owner, as on 2026-11-08 16:38), and the owner's whispered words go back on the same connection."""
    import websockets
    from app.services import voice_sideband as S, voice_stage, voice_calls, voice_prefetch, voice_lookup
    monkeypatch.setattr(voice_stage, 'ROOT', tmp_path)
    monkeypatch.setattr(voice_prefetch, 'enabled', lambda: False)
    monkeypatch.setattr(voice_calls, 'begin', lambda *a: None)
    monkeypatch.setattr(voice_calls, 'end', lambda *a: None)
    monkeypatch.setattr(S, 'note', lambda *a, **kw: None)
    async def idle(*a, **k): await asyncio.Event().wait()
    for name in ('job_feed', 'chat_feed', 'summon_feed', 'finish_call', 'call_log'):
        monkeypatch.setattr(S, name, idle if name.endswith('feed') else (lambda *a, **k: asyncio.sleep(0)))
    monkeypatch.setattr(voice_lookup, 'open_call', lambda *a, **k: SimpleNamespace(router=None, lookups={}, closed=False, close=lambda: None, user_id='u', room_id='r'))
    monkeypatch.setattr(voice_lookup, 'close_call', lambda call: None)
    monkeypatch.setattr(W, 'reading', lambda audio: ('明日って何曜日？', ''))
    monkeypatch.setattr(W, 'ANSWER_WAIT_S', 0)
    events = [{'type': 'session.started', 'session': {'id': 'call-w'}}]
    events += [{'type': 'session.input_audio.append', 'audio': part} for part in chunks(np.concatenate([floor(2), whisper(1.5), floor(1.4)]))]
    out = []
    class Socket:
        count = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def send(self, text): out.append(json.loads(text))
        async def recv(self):
            if self.count < len(events):
                self.count += 1
                return json.dumps(events[self.count - 1])
            for _ in range(60):
                if any(e.get('type') == 'session.instructions.append' for e in out): break
                await asyncio.sleep(.05)
            return json.dumps({'type': 'session.closed'})
    monkeypatch.setattr(websockets, 'connect', lambda *a, **kw: Socket())
    await S._run('call-w', 'u', 'r', 'key', True)
    given = [e for e in out if e.get('type') == 'session.instructions.append']
    assert len(given) == 1 and '「明日って何曜日？」' in given[0]['content'] and given[0]['delegation_id'] is None
    spoken = [e for e in out if e.get('type') == 'session.commentary.append']
    assert len(spoken) == 1 and '「明日って何曜日？」' in spoken[0]['content']
    assert not any(e.get('type') == 'response.create' for e in out)
