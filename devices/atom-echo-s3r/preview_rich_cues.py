"""Audition only: warm mono chord cues. Does not update or contact the device."""
import argparse
import math
from pathlib import Path
import struct
import wave

RATE = 48000


def render(standby=False):
    # Keep the body below 350 Hz; soft, quiet overtones rather than a whistle.
    notes = (261.6256, 220.0, 174.6141) if standby else (196.0, 246.9417, 293.6648)
    length = 1.05 if standby else 1.15
    dry = []
    for i in range(round(length * RATE)):
        t = i / RATE
        value = 0.
        for n, frequency in enumerate(notes):
            age = t - n * .032
            if age < 0:
                continue
            attack = (1 - math.exp(-age / .025)) ** 2
            decay = math.exp(-age / (.22 if standby else .27))
            tail = min(1., max(0., (length - t) / .17))
            envelope = attack * decay * (.5 - .5 * math.cos(math.pi * tail))
            phase = 2 * math.pi * frequency * age
            # Gentle detuning adds width while staying compatible with mono.
            tone = (.84 * math.sin(phase)
                    + .13 * math.sin(phase * 1.0025 + .2)
                    + .03 * math.sin(phase * 2))
            value += envelope * tone * (1. if n == 0 else .72)
        dry.append(value)
    # Short diffuse tail with no bright noise or discrete echo.
    mixed = dry.copy()
    for delay, amount in ((.037, .15), (.071, .09), (.113, .05)):
        offset = round(delay * RATE)
        for i in range(offset, len(mixed)):
            mixed[i] += dry[i - offset] * amount
    # Fade the final tail and normalize both cues to comparable body loudness.
    for i in range(len(mixed) - 2400, len(mixed)):
        mixed[i] *= .5 - .5 * math.cos(math.pi * (len(mixed) - 1 - i) / 2400)
    rms = math.sqrt(sum(v*v for v in mixed) / len(mixed))
    gain = min(5300 / rms, 20000 / max(map(abs, mixed)))
    return [round(v * gain) for v in mixed]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    samples = [0] * 9600
    for label, standby in (('ready', False), ('standby', True)):
        cue = render(standby)
        print(label, 'peak=', max(map(abs, cue)),
              'rms=', round(math.sqrt(sum(v*v for v in cue) / len(cue))))
        samples.extend(cue)
        samples.extend([0] * 38400)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.output), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(struct.pack('<%dh' % len(samples), *samples))
    with wave.open(str(args.output), 'rb') as check:
        assert check.getnframes() == len(samples)
        assert check.getframerate() == RATE
    print(args.output)


if __name__ == '__main__':
    main()
