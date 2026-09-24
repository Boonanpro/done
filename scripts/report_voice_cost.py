"""What each phone call cost, from the server's call log (.tmp/voice-sideband.jsonl): Live 1 by the minute, the backend
(Responses delegation) by its recorded tokens. Recorded from 2026-09-24; earlier calls show the Live part only.

Usage: python scripts/report_voice_cost.py [days=7]
Prices (OpenAI, per 1M tokens / per minute): gpt-live-1 $0.05/min; gpt-5.6-terra input $2, cached $0.2, output $12."""
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / '.tmp' / 'voice-sideband.jsonl'
LIVE_PER_MINUTE = 0.05
BACKEND = {'gpt-5.6-terra': (2.0, 0.2, 12.0)}


def main(days=7):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = []
    for path in (LOG.with_suffix('.previous.jsonl'), LOG):
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    tokens = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        if r.get('phase') == 'backend_completed' and 'input_tokens' in r:
            t = tokens[r.get('session_id')]
            price = BACKEND.get(str(r.get('model', '')).split('-2')[0], BACKEND['gpt-5.6-terra'])
            t[0] += r['input_tokens']; t[1] += r['cached_tokens']; t[2] += r['output_tokens']
            t[3] += ((r['input_tokens'] - r['cached_tokens']) * price[0] + r['cached_tokens'] * price[1] + r['output_tokens'] * price[2]) / 1e6
    total_live = total_backend = 0
    for r in rows:
        if r.get('phase') != 'sideband_closed' or (r.get('at') or '') < since or not r.get('seconds'):
            continue
        live = r['seconds'] / 60 * LIVE_PER_MINUTE
        t = tokens.get(r.get('session_id'))
        backend = t[3] if t else None
        total_live += live; total_backend += backend or 0
        print(f"{r['at'][:16]}  {r['seconds']:5}s  Live ${live:.3f}  backend " + (f"${backend:.3f} (in {t[0]}, cached {t[1]}, out {t[2]})" if t else 'not recorded'))
    print(f'total: Live ${total_live:.2f} + backend ${total_backend:.2f} (recorded calls only)')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
