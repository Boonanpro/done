"""One inactivity clock per device intent, preserved through reconnects."""
import time


class VoiceIdle:
    def __init__(self, timeout=600, clock=time.monotonic):
        self.clock, self.timeout = clock, timeout
        self.reset()

    def reset(self):
        self.last_speech = self.clock()

    def speech(self):
        self.last_speech = self.clock()

    def expired(self):
        return self.clock() - self.last_speech >= self.timeout
