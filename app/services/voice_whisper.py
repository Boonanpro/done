"""A whisper the speech model does not hear, heard by this server and handed to it as words.

Why: GPT-Live takes no input settings (turn detection, sensitivity, transcription are fixed), and a whisper through the
owner's earbuds (PineBuds Pro, in-ear mic firmware) is mostly not taken as speech: 2026-09-26〜30 the phone sent
whispers lifted by up to +30 dB and in nine calls Live left most of them unanswered (「1たす1の答えを教えてください」,
「聞こえないですか？」), and 2026-11-08 16:38 a 13 s call of whispers had no speech start at all. The same recordings,
cut where the owner spoke and transcribed by Whisper on this Mac, read back as the words that were said in 15 of 28.

How: the sideband receives a copy of the call's input audio (session.input_audio.append, mono PCM16 at 24 kHz, no
timestamps). Each 20 ms is measured against the input's own noise floor; a stretch of speech that ends in 0.7 s of quiet
is a candidate. Only unvoiced speech is kept: a whisper has no voice pitch, while the owner's ordinary voice, Dan's own
voice coming back through the earbuds and a television or people nearby all have one (and Live hears or ignores those
itself, as it should). The candidate is transcribed on this Mac's GPU (Whisper large-v3-turbo through MLX,
scripts/voice_whisper_worker.py, about 0.3 s; no audio leaves the server), and if Live has not heard words of its own
meanwhile, the owner's words are given to the speech model with session.instructions.append, the documented way to tell
it what to do now. OpenAI's own transcription read the same whispers as words of other languages (2026-11-08).

Switch: DAN_VOICE_WHISPER=0 turns it off. Audio is held in memory for the length of one utterance and never written.
"""
import asyncio
import base64
import json
import logging
import os
import re
import threading
import time

import numpy as np

logger = logging.getLogger(__name__)
RATE = 24000                 # the reflected input: mono PCM16LE at 24 kHz whatever the call's own transport
FRAME = RATE // 50           # 20 ms
ABOVE_FLOOR_DB = 8.0         # a frame is speech this far above the input's own noise floor
FLOOR_FRAMES = 250           # the floor is read from the last 5 s
MIN_LEVEL_DB = -68.0         # ...and above digital silence (dBFS of the band energy)
START_FRAMES, START_WINDOW = 3, 5
END_QUIET_FRAMES = 35        # 0.7 s of quiet ends an utterance
PRE_ROLL_FRAMES = 15         # 0.3 s kept before the first speech frame (a whisper starts softly)
TAIL_FRAMES = 10             # 0.2 s of the closing quiet kept
MIN_SPEECH_FRAMES = 12       # 0.24 s of speech at least
MAX_FRAMES = 50 * 12         # one utterance is at most 12 s
MAX_VOICED = 0.35            # more voiced frames than this: ordinary voice, not a whisper
LIVE_GRACE_S = 1.0           # Live's own words this soon around an utterance mean Live heard it
DAN_GUARD_S = 1.0            # this soon after Dan's voice, input is his voice coming back (the phone's echo arrives 0.3〜0.6 s late)
DAN_AUDIBLE_DB = -45.0       # Dan's output this loud is heard in the in-ear mic
ANSWER_WAIT_S = 6.0          # the speech model has answered a whisper when Dan speaks within this
MIN_LOGPROB = -0.8           # below this Whisper was guessing: the readings this unsure on the 2026-09 calls were wrong
# Whisper's known inventions on quiet or empty audio (the recordings of 2026-09-24〜30 produced each of these).
INVENTED = re.compile(r'^(ご視聴(いただき)?ありがとうございました|ありがとうございました|ご協力ありがとうございました|お疲れ様でした|'
                      r'おやすみなさい|ごちそうさまでした|お待ちしております|(また|次の動画で|次回)(来週)?お会いしましょう|'
                      r'次回予告|以上で終わります|チャンネル登録.*|字幕.*|ん+|う+ん|あ+|え+)[。、.!！?？\s]*$')

LOOP = re.compile(r'(.{2,8}?)[、。\s]*(?:\1[、。\s]*){2,}')   # a phrase three times over: Whisper looping on noise


def enabled():
    return os.environ.get('DAN_VOICE_WHISPER', '1') != '0'


_band = None


def _features(frame, previous):
    """(band level in dBFS, voiced) for one 20 ms frame; voiced = a pitch 75〜400 Hz in the last 40 ms."""
    global _band
    spectrum = np.abs(np.fft.rfft(frame * np.hanning(len(frame)), 512)) ** 2
    if _band is None:
        freqs = np.fft.rfftfreq(512, 1 / RATE)
        _band = (freqs >= 250) & (freqs <= 7000)
    level = 10 * np.log10(spectrum[_band].sum() / len(frame) ** 2 * 4 + 1e-12)
    window = np.concatenate([previous, frame])
    low = window.reshape(-1, 3).mean(axis=1)           # 8 kHz is enough for a pitch; the averaging is its low-pass
    low = low - low.mean()
    energy = float((low * low).sum())
    if energy <= 1e-10:
        return level, False
    spec = np.fft.rfft(low, 2 * len(low))
    corr = np.fft.irfft(spec * np.conj(spec))[:len(low)] / energy
    lo, hi = 8000 // 400, 8000 // 75
    return level, bool(corr[lo:hi].max() > 0.55)


class Ear:
    """Cuts the reflected input into utterances and keeps the whispered ones. Feed audio(); utterances come out of
    take() as (audio float32 at 24 kHz, start_wall, end_wall, voiced_ratio, speech_seconds)."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.rest = np.zeros(0, dtype=np.float32)
        self.previous = np.zeros(FRAME, dtype=np.float32)
        self.floor = None
        self.levels = []
        self.recent = []           # speech flags of the last START_WINDOW frames
        self.history = []          # the last PRE_ROLL_FRAMES frames while not in an utterance
        self.frames = None         # the utterance being collected
        self.flags = []
        self.quiet = 0
        self.began = 0.0
        self.out = []
        self.samples = 0           # input samples seen: the wall time of a frame is taken from the clock at arrival

    def audio(self, payload):
        data = base64.b64decode(payload) if isinstance(payload, str) else payload
        pcm = np.frombuffer(data, dtype='<i2').astype(np.float32) / 32768.0
        self.feed(pcm)

    def feed(self, pcm):
        buffer = np.concatenate([self.rest, pcm])
        whole = len(buffer) // FRAME * FRAME
        now = self.clock()
        count = whole // FRAME
        for index in range(count):
            frame = buffer[index * FRAME:(index + 1) * FRAME]
            # this frame's wall time: the chunk arrives at real-time pace, its frames end at `now`
            self._frame(frame, now - (count - 1 - index) * 0.02)
        self.rest = buffer[whole:]

    def _frame(self, frame, at):
        level, voiced = _features(frame, self.previous)
        self.previous = frame
        # The noise floor: the quietest tenth of the last 5 s (digital silence left out). A whisper through the in-ear mic
        # stood only 10〜15 dB above the quiet between sentences (whisper-both-ears-fbmic, 2026-09-25).
        if level > -95:
            self.levels.append(level)
            if len(self.levels) > FLOOR_FRAMES: del self.levels[0]
        if len(self.levels) >= 10 and len(self.levels) % 5 == 0 or self.floor is None:
            self.floor = float(np.percentile(self.levels, 10)) if self.levels else level
        speech = level > self.floor + ABOVE_FLOOR_DB and level > MIN_LEVEL_DB
        self.recent = (self.recent + [speech])[-START_WINDOW:]
        if self.frames is None:
            self.history = (self.history + [(frame, speech, voiced)])[-PRE_ROLL_FRAMES:]
            if sum(self.recent) >= START_FRAMES:
                self.frames = [f for f, _, _ in self.history]
                self.flags = [(s, v) for _, s, v in self.history]
                self.began = at - 0.02 * len(self.frames)
                self.quiet = 0
            return
        self.frames.append(frame)
        self.flags.append((speech, voiced))
        self.quiet = 0 if speech else self.quiet + 1
        if self.quiet >= END_QUIET_FRAMES or len(self.frames) >= MAX_FRAMES:
            self._close(at)

    def _close(self, at):
        frames, flags = self.frames, self.flags
        self.frames, self.flags, self.history, self.recent = None, [], [], []
        speech = [v for s, v in flags if s]
        if len(speech) < MIN_SPEECH_FRAMES:
            return
        voiced = sum(speech) / len(speech)
        cut = len(frames) - max(0, self.quiet - TAIL_FRAMES)    # keep some of the closing quiet
        self.out.append((np.concatenate(frames[:cut]), self.began, at - 0.02 * self.quiet, round(voiced, 2), round(len(speech) * 0.02, 2)))

    def take(self):
        out, self.out = self.out, []
        return out


def to_16k(audio):
    """24 kHz -> 16 kHz (2 up, 3 down) through a windowed-sinc low-pass; numpy only."""
    taps = 95
    n = np.arange(taps) - (taps - 1) / 2
    h = (np.sinc(n / 3) * np.hamming(taps)).astype(np.float32)
    h /= h.sum()
    up = np.zeros(len(audio) * 2, dtype=np.float32)
    up[::2] = audio * 2
    return np.convolve(up, h, mode='same')[::3].astype(np.float32)


WORKER_PYTHON = os.environ.get('DAN_VOICE_WHISPER_PYTHON', '/Users/mikihonda/whisper-mlx-venv/bin/python')
WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts', 'voice_whisper_worker.py')
_worker = None
_worker_lock = threading.Lock()
_fallback = None


def _start_worker():
    """The GPU transcriber (scripts/voice_whisper_worker.py) in its own environment, kept for the process's life."""
    global _worker
    if _worker is not None and _worker.poll() is None:
        return _worker
    import subprocess
    _worker = subprocess.Popen([WORKER_PYTHON, os.path.abspath(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, bufsize=1)
    ready = _worker.stdout.readline()
    if '"ready"' not in ready:
        _worker.kill(); _worker = None
        raise RuntimeError('whisper worker did not start')
    return _worker


def _segments_gpu(x):
    with _worker_lock:
        worker = _start_worker()
        worker.stdin.write(json.dumps({'id': 1, 'pcm': base64.b64encode(x.astype(np.float32).tobytes()).decode()}) + chr(10))
        worker.stdin.flush()
        answer = json.loads(worker.stdout.readline() or '{}')
    if 'segments' not in answer:
        raise RuntimeError(answer.get('error') or 'whisper worker gave no answer')
    return answer['segments']


def _segments_cpu(x):
    """Without the GPU environment: faster-whisper on the CPU (the lifelog's model), 2.6〜3.3 s an utterance."""
    global _fallback
    with _worker_lock:
        if _fallback is None:
            from faster_whisper import WhisperModel
            _fallback = WhisperModel('mobiuslabsgmbh/faster-whisper-large-v3-turbo', device='cpu', compute_type='int8',
                                     cpu_threads=os.cpu_count() or 4)
        segments, _ = _fallback.transcribe(x, language='ja', beam_size=1, vad_filter=False, condition_on_previous_text=False,
                                           without_timestamps=True)
        return [{'text': s.text, 'avg_logprob': s.avg_logprob, 'no_speech_prob': s.no_speech_prob,
                 'compression_ratio': s.compression_ratio} for s in segments]


def _gpu():
    return os.path.exists(WORKER_PYTHON)


def warm():
    """Start the transcriber off the call's path (its model loads in a few seconds, once per process)."""
    if enabled() and _gpu():
        def start():
            try:
                with _worker_lock: _start_worker()
            except Exception as exc:
                logger.warning('voice whisper worker not started: %s', exc)
        threading.Thread(target=start, daemon=True, name='voice-whisper-warm').start()


def transcribe(audio):
    """Words of one utterance (24 kHz float), or '' when what Whisper heard is not trustworthy."""
    x = to_16k(audio)
    peak = float(np.abs(x).max()) or 1.0
    x = (x / peak * 0.5).astype(np.float32)
    segments = _segments_gpu(x) if _gpu() else _segments_cpu(x)
    words, sure = [], 0.0
    for segment in segments:
        if segment['no_speech_prob'] > 0.6 or segment['avg_logprob'] < MIN_LOGPROB or segment['compression_ratio'] > 2.4:
            continue
        words.append(str(segment['text']).strip())
        sure = min(sure, segment['avg_logprob'])
    text = ''.join(words).strip()
    if not text or INVENTED.match(text) or LOOP.search(text):
        return ''
    if len(re.sub(r'[。、.!！?？\s]', '', text)) <= 3 and sure < -0.5:   # a lone 「はい」 out of noise: read that unsure, it was not said
        return ''
    return text


def as_heard(text):
    """What the speech model is given: the owner's words, as the owner's. Nothing about how they came (11/7: whatever
    it is given, it talks about)."""
    return f'本人の今の発言です。聞こえていたのと同じように、この発言にそのまま応じてください：「{text}」'


class Listener:
    """The sideband's part: audio in, the owner's whispered words out to the speech model."""

    def __init__(self, send, record, dialogue=None, spoke=None, clock=time.monotonic, transcriber=None, on_words=None):
        self.send, self.record, self.dialogue, self.on_words = send, record, dialogue, on_words
        self.spoke = spoke if spoke is not None else {}
        self.clock = clock
        self.ear = Ear(clock)
        self.transcriber = transcriber or transcribe
        self.live_heard = []         # wall times of Live's own transcript of the owner
        self.dan_until = 0.0         # Dan's voice is audible (in the earbuds, so in their mic) until then
        self.tasks = set()
        self.closed = False
        self.warmed = False

    def audio(self, payload):
        """A reflected input chunk (session.input_audio.append)."""
        if self.closed:
            return
        if not self.warmed:   # the call's audio has begun: the transcriber starts now, before the first whisper
            self.warmed = True
            warm()
        try:
            self.ear.audio(payload)
        except Exception as exc:
            self.record('whisper_failed', stage='audio', error_type=type(exc).__name__)
            return
        for item in self.ear.take():
            task = asyncio.get_running_loop().create_task(self._utterance(*item))
            self.tasks.add(task); task.add_done_callback(self.tasks.discard)

    def dan_audio(self, payload):
        """A reflected output chunk (session.output_audio.delta): silence comes too, only a loud one counts."""
        try:
            data = base64.b64decode(payload) if isinstance(payload, str) else payload
            pcm = np.frombuffer(data, dtype='<i2').astype(np.float32) / 32768.0
        except Exception:
            return
        if len(pcm) and 10 * np.log10(float((pcm * pcm).mean()) + 1e-12) > DAN_AUDIBLE_DB:
            self.dan_until = max(self.dan_until, self.clock()) + len(pcm) / RATE

    def heard(self):
        """Live wrote down words of the owner: it heard them itself."""
        now = self.clock()
        self.live_heard = [t for t in self.live_heard if now - t < 30] + [now]

    def _live_heard(self, began, ended):
        return any(began - LIVE_GRACE_S <= t <= ended + LIVE_GRACE_S for t in self.live_heard)

    def _dan_speaking(self, began, ended):
        words = self.spoke.get('dan_words', 0)
        return (bool(words) and words >= began - DAN_GUARD_S) or self.dan_until >= began - DAN_GUARD_S

    async def _utterance(self, audio, began, ended, voiced, speech_s):
        if voiced > MAX_VOICED:
            self.record('whisper_skipped', why='voiced', voiced=voiced, speech_s=speech_s)
            return
        if self._dan_speaking(began, ended):
            self.record('whisper_skipped', why='dan_speaking', voiced=voiced, speech_s=speech_s)
            return
        t0 = time.monotonic()
        try:
            text = await asyncio.to_thread(self.transcriber, audio)
        except Exception as exc:
            self.record('whisper_failed', stage='transcribe', error_type=type(exc).__name__, detail=str(exc)[:160])
            return
        ms = round((time.monotonic() - t0) * 1000)
        if self.closed:
            return
        if not text:
            self.record('whisper_skipped', why='no_words', voiced=voiced, speech_s=speech_s, transcribe_ms=ms)
            return
        if self._live_heard(began, ended):
            self.record('whisper_skipped', why='live_heard', voiced=voiced, speech_s=speech_s, transcribe_ms=ms, chars=len(text))
            return
        if self._dan_speaking(began, ended):
            self.record('whisper_skipped', why='dan_speaking', voiced=voiced, speech_s=speech_s, transcribe_ms=ms)
            return
        if self.dialogue is not None:
            self.dialogue.add('user', text)
        if self.on_words is not None:   # what listens to the owner's words on this server (a whispered 「電話切って」 ends the call)
            try: self.on_words(text)
            except Exception as exc: self.record('whisper_failed', stage='on_words', error_type=type(exc).__name__)
        sent = self.clock()
        await self.send({'type': 'session.instructions.append', 'event_id': f'dan-whisper-{time.time_ns()}', 'delegation_id': None,
                         'content': as_heard(text)})
        self.record('whisper_heard', voiced=voiced, speech_s=speech_s, transcribe_ms=ms, chars=len(text),
                    after_end_ms=round((sent - ended) * 1000))
        # Whether the speech model answered: not known before a real call (2026-11-08), so the next call's log says it.
        await asyncio.sleep(ANSWER_WAIT_S)
        answered = max(self.spoke.get('dan_words', 0), self.dan_until) > sent
        self.record('whisper_answered' if answered else 'whisper_unanswered')

    def close(self):
        self.closed = True
        for task in self.tasks:
            task.cancel()
