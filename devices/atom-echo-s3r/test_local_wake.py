import unittest
from local_wake import matches_wake, WakeDecoder
import json


class WakeTests(unittest.TestCase):
    def test_early_candidate_must_pass_confidence_and_rejection_keeps_final_path(self):
        class Recognizer:
            def __init__(self, confidence): self.confidence = confidence; self.final = False
            def Reset(self): pass
            def SetWords(self, enabled): pass
            def AcceptWaveform(self, pcm): return self.final
            def PartialResult(self): return json.dumps({'partial':'hey dan'})
            def Result(self): return self.FinalResult()
            def FinalResult(self): return json.dumps({'result':[{'word':'hey','conf':1}, {'word':'dan','conf':self.confidence}]})
        primary, verifier = Recognizer(1), Recognizer(.5)
        decoder = WakeDecoder(primary, verifier, ['hey dan'])
        self.assertFalse(any(decoder.feed(bytes(320)) for _ in range(20)))
        primary.final = True
        self.assertTrue(decoder.feed(bytes(320)))
        primary.final = False
        verifier.confidence = 1
        decoder.reset()
        self.assertFalse(any(decoder.feed(bytes(320)) for _ in range(12)))
        self.assertTrue(decoder.feed(bytes(320)))

    def test_phrase_requires_confident_prefix_not_generic_speech(self):
        def result(*words): return {'result':[{'word':w,'conf':.95} for w in words]}
        self.assertTrue(matches_wake(result('hey','dan'),['hey dan']))
        self.assertTrue(matches_wake(result('hey','dan','[unk]'),['hey dan']))
        self.assertFalse(matches_wake(result('dan'),['hey dan']))
        self.assertFalse(matches_wake(result('[unk]','hey','dan'),['hey dan']))
        self.assertFalse(matches_wake(result('hey','john'),['hey dan']))
        self.assertFalse(matches_wake({'result':[{'word':'hey','conf':.5},{'word':'dan','conf':.9}]},['hey dan']))
        self.assertFalse(matches_wake({},['hey dan']))
        self.assertTrue(matches_wake(result('hello','dan'),['hey dan','hello dan']))


if __name__ == '__main__': unittest.main()
