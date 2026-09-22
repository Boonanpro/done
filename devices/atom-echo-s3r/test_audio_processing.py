"""Synthetic acoustic-path regression; no microphone, API or chat access."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '.tmp/atom-aec-tools'))
import numpy as np
from pywebrtc_audio import AudioProcessor


class EchoTests(unittest.TestCase):
    def test_echo_removed_and_simultaneous_near_voice_preserved(self):
        rate = 48000
        n = rate * 20
        rng = np.random.default_rng(42)
        far = np.convolve(rng.normal(0, 2500, n), np.ones(5) / 5, 'same')
        near = np.zeros(n)
        near[1920:] = .6 * far[:-1920]  # 40 ms simulated acoustic/buffer delay
        t = np.arange(n) / rate
        voice = 1200 * (np.sin(2*np.pi*220*t) + .5*np.sin(2*np.pi*440*t)) * (.5+.5*np.sin(2*np.pi*3*t))
        near[rate*15:] += voice[rate*15:]
        near, far = near.astype(np.int16), far.astype(np.int16)
        ap = AudioProcessor(sample_rate=rate, echo_cancellation=True,
                            noise_suppression=True, ns_level=1, stream_delay_ms=40)
        out = np.concatenate([ap.process(near[i:i+480], far[i:i+480]) for i in range(0, n, 480)])
        rms = lambda x: np.sqrt(np.mean(x.astype(float)**2))
        attenuation = 20*np.log10(rms(near[rate*10:rate*14]) / max(1, rms(out[rate*10:rate*14])))
        voice_ratio = rms(out[rate*17:]) / rms(voice[rate*17:])
        self.assertGreater(attenuation, 12, 'Echo-only audio must be attenuated')
        self.assertGreater(voice_ratio, .5, 'Simultaneous near-end voice must survive')
        self.assertLess(voice_ratio, 1.5, 'Processing must not excessively amplify near voice')
        print(f'echo attenuation={attenuation:.1f} dB; near voice RMS ratio={voice_ratio:.2f}')


if __name__ == '__main__':
    unittest.main()
