"""Run right after Dan core starts: does work asked through an entry actually come back with a result?

On 2026-09-27 a one-line import slip made every job started from a call fail the instant it began; nothing checked a
real job after the restart, and the owner found out on 9/28 when paying an invoice by voice failed twice. Health
endpoints answered 200 the whole time. This asks for one small, harmless piece of work the way a call does, in the
test room, and waits for its result.

Usage: python scripts/verify_dan.py        exit 0 = passed, 1 = failed (the reason is printed)
"""
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')

USER = '2582a188-ff24-4a4f-b989-6063034d90b2'
TEST_ROOM = '38461f5a-6ded-464a-adb9-92a7de46b288'   # 「Epic Gamesログインと認証設定」: the room tests may use
TASK = '動作確認: 今日の日付と曜日だけを一文で答えて。道具やブラウザは使わない。'
LIMIT = 180


def health():
    import urllib.request
    bad = []
    for port in (9000, 8000):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=5) as r:
                if r.status != 200: bad.append(f'{port}: {r.status}')
        except Exception as exc:
            bad.append(f'{port}: {type(exc).__name__}')
    return bad


async def voice_work():
    from app.services import voice_responses, command_job_state as state
    started = time.monotonic()
    out = await voice_responses.run_function('start_work', {'task': TASK}, USER, TEST_ROOM, [])
    job_id = out.get('job_id')
    if not out.get('accepted') or not job_id:
        return f'not accepted: {out}'
    while time.monotonic() - started < LIMIT:
        s = state.read(job_id)
        if s and s['state'] in state.TERMINAL:
            break
        await asyncio.sleep(2)
    s = state.read(job_id) or {}
    if s.get('state') != 'completed' or not str(s.get('result') or '').strip():
        return f"job {job_id[:8]} {s.get('state', 'missing')}: {str(s.get('error') or s.get('result') or '')[:300]}"
    print(f'voice work: completed in {time.monotonic() - started:.0f}s -> {str(s["result"])[:120]}')
    return None


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    problems = [f'health {b}' for b in health()]
    if not problems:
        failure = asyncio.run(voice_work())
        if failure: problems.append('voice work ' + failure)
    if problems:
        print('FAILED: ' + ' / '.join(problems))
        sys.exit(1)
    print('PASSED')


if __name__ == '__main__':
    main()
