import unittest
from voice_idle import VoiceIdle


class IdleTests(unittest.TestCase):
    def test_silence_expires_at_ten_minutes(self):
        now = [0]
        idle = VoiceIdle(clock=lambda: now[0])
        now[0] = 599
        self.assertFalse(idle.expired())
        now[0] = 600
        self.assertTrue(idle.expired())

    def test_speech_extends_but_connection_does_not(self):
        now = [0]
        idle = VoiceIdle(clock=lambda: now[0])
        now[0] = 500
        idle.speech()
        now[0] = 1000
        self.assertFalse(idle.expired())
        now[0] = 1100
        self.assertTrue(idle.expired())
