"""Offline PC wake phrase detection. Audio/text never saved or sent to a service."""
import audioop
import json
from pathlib import Path
import queue
import sys
import threading
import time
from collections import deque

ROOT = Path(__file__).resolve().parents[2]


def matches_wake(result, phrases):
    words = result.get('result') or []
    for phrase in phrases:
        tokens = phrase.lower().split()
        prefix = words[:len(tokens)]
        if len(prefix) == len(tokens) and [w.get('word') for w in prefix] == tokens and all(w.get('conf', 0) >= .8 for w in prefix):
            return True
    return False


class LocalWake:
    def __init__(self, callback, phrases=None):
        sys.path.insert(0, str(ROOT / '.tmp/atom-wake-tools'))
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
        self.phrases = phrases or ['hey dan']
        model = Model(str(ROOT / '.tmp/atom-wake-models/vosk-model-small-en-us-0.15'))
        self.recognizer = KaldiRecognizer(model, 16000, json.dumps([*self.phrases, '[unk]']))
        self.recognizer.SetWords(True)
        self.decoder = WakeDecoder(self.recognizer, KaldiRecognizer(model, 16000, json.dumps([*self.phrases, '[unk]'])), self.phrases)
        self.callback = callback
        # TCP may deliver a short Wi-Fi backlog in a burst. Keep up to two
        # seconds instead of resetting recognition on every 300 ms burst.
        self.queue = queue.Queue(maxsize=200)
        self.stats = {'frames':0,'processed':0,'dropped':0,'results':0,'detected':0}
        self.stopped = threading.Event()
        self.generation = 0
        self.cooldown = time.monotonic() + 2
        self.thread = threading.Thread(target=self.run, name='atom-local-wake', daemon=True)
        self.thread.start()

    def reset(self, cooldown=0):
        self.generation += 1
        self.cooldown = time.monotonic() + cooldown

    def feed(self, pcm, intent):
        if time.monotonic() < self.cooldown: return
        self.stats['frames']+=1
        try: self.queue.put_nowait((self.generation, time.monotonic(), intent, pcm))
        except queue.Full:
            self.stats['dropped']+=1
            self.reset(.5)

    def run(self):
        generation = -1
        conversion = None
        while not self.stopped.is_set():
            try: item = self.queue.get(timeout=.2)
            except queue.Empty: continue
            epoch, captured, intent, pcm = item
            if epoch != self.generation or time.monotonic()-captured > 2:
                self.stats['dropped']+=1
                continue
            self.stats['processed']+=1
            if epoch != generation:
                self.decoder.reset(); conversion = None; generation = epoch
            downsampled, conversion = audioop.ratecv(pcm, 2, 1, 48000, 16000, conversion)
            detected = self.decoder.feed(downsampled)
            self.stats['results'] = self.decoder.results
            if detected and epoch == self.generation:
                self.stats['detected']+=1
                self.reset(3)
                self.callback(intent)

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=2)

    def status(self):
        return {**self.stats,'worker_alive':self.thread.is_alive(),'queued':self.queue.qsize()}


class WakeDecoder:
    """Score a stable early candidate without consuming the ongoing recognition.

    The verifier uses the same audio and confidence rule as final recognition.
    A rejected early candidate leaves the primary recognizer free to hear more.
    """
    def __init__(self, primary, verifier, phrases):
        self.primary, self.verifier, self.phrases = primary, verifier, phrases
        self.verifier.SetWords(True)
        self.results = 0
        self.reset()

    def reset(self):
        self.primary.Reset()
        self.frames = deque(maxlen=200)  # two seconds of 10 ms frames at 16 kHz
        self.samples = 0
        self.candidate = None
        self.since = 0
        self.checked = -100000

    def feed(self, pcm):
        self.frames.append(pcm)
        self.samples += len(pcm) // 2
        if self.primary.AcceptWaveform(pcm):
            result = json.loads(self.primary.Result())
            self.results += 1
            self.frames.clear()
            self.candidate = None
            return matches_wake(result, self.phrases)
        words = json.loads(self.primary.PartialResult()).get('partial', '').split()
        candidate = next((p for p in self.phrases if words[:len(p.split())] == p.split()), None)
        if candidate != self.candidate:
            self.candidate, self.since = candidate, self.samples
        if candidate and self.samples-self.since >= 1920 and self.samples-self.checked >= 3840:
            self.checked = self.samples
            self.verifier.Reset()
            self.verifier.AcceptWaveform(b''.join(self.frames))
            result = json.loads(self.verifier.FinalResult())
            self.results += 1
            return matches_wake(result, self.phrases)
        return False
