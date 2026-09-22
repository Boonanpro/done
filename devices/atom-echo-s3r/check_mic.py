"""Read microphone peak/clipping counters; never stores microphone audio."""
import argparse
import datetime
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '.tmp/atom-audio-tools'))
import serial
from serial.tools import list_ports

p = argparse.ArgumentParser()
p.add_argument('--gain', type=int, choices=[0, 12, 18, 24], default=18)
p.add_argument('--seconds', type=float, default=8)
p.add_argument('--label', default='unspecified distance')
args = p.parse_args()
if not 1 <= args.seconds <= 30:
    p.error('--seconds must be 1 through 30')
ports = [port for port in list_ports.comports() if port.vid == 0x303A and port.pid == 0x8001]
if len(ports) != 1:
    raise SystemExit('Connect the Atom USB application interface first; no device was modified.')
with serial.Serial(ports[0].device, 115200, timeout=.5) as device:
    device.write({0: b'x', 12: b'u', 18: b'v', 24: b'w'}[args.gain])
    device.read(1024)
    device.write(b'z')
    print('Measuring microphone level for', args.seconds, 'seconds; gain', args.gain, 'dB', flush=True)
    time.sleep(args.seconds)
    device.write(b'?N')
    report = device.read(2048).decode('utf-8', errors='replace')
result = {'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'gain_db': args.gain, 'seconds': args.seconds, 'label': args.label,
          'diagnostics': report}
with (Path(__file__).parent / 'mic-measurements.jsonl').open('a', encoding='utf-8') as log:
    log.write(json.dumps(result, ensure_ascii=False) + '\n')
print(report)
