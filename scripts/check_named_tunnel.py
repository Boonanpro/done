"""Verify the public Dan route and real SSE delivery without posting messages.

Use --wait-seconds while DNS delegation and TLS certificates are propagating.
Credentials remain local; the output contains status and timings only.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'devices' / 'atom-echo-s3r'))
from voice_credentials import load_credentials


async def check():
    base = 'https://dan.paina.info'
    result = {'hostname': 'dan.paina.info', 'checked_at': time.time()}
    async with httpx.AsyncClient(timeout=25) as client:
        started = time.monotonic()
        response = await client.get(base + '/login')
        response.raise_for_status()
        assert 'text/html' in response.headers.get('content-type', '')
        result['login_ms'] = round((time.monotonic() - started) * 1000)
        response = await client.get(base + '/')
        location = response.headers.get('location', '')
        assert response.status_code in (301, 302, 307, 308)
        assert location == '/login' or location == base + '/login', 'Wrong redirect host'
        response = await client.get(base + '/api/v1/chat/me')
        assert response.status_code == 401, 'Anonymous protected API must be denied'
        result['anonymous_denied'] = True
        auth = await load_credentials(ROOT / '.tmp/atom-headless-auth.json', 'http://127.0.0.1:9000')
        headers = {'Authorization': 'Bearer ' + auth['token']}
        response = await client.get(base + '/api/v1/chat/me', headers=headers)
        response.raise_for_status()
        result['authenticated_me'] = True
        started = time.monotonic()
        first = None
        async with client.stream('GET', base + '/api/v1/chat/feed', headers=headers, timeout=40) as response:
            response.raise_for_status()
            assert 'text/event-stream' in response.headers.get('content-type', '')
            async for line in response.aiter_lines():
                elapsed = time.monotonic() - started
                if line == 'event: hello':
                    first = elapsed
                    result['sse_hello_ms'] = round(elapsed * 1000)
                elif line.startswith(': ping') and first is not None:
                    result['sse_ping_ms'] = round(elapsed * 1000)
                    assert elapsed - first > 1, 'SSE hello and heartbeat were buffered together'
                    result['sse_streaming_verified'] = True
                    break
            else:
                raise RuntimeError('Stream closed without a heartbeat')
    return result


async def main(args):
    deadline = time.monotonic() + args.wait_seconds
    output = ROOT / '.tmp/dan-named-tunnel-public-check.json'
    while True:
        try:
            result = await check()
            result['ok'] = True
        except Exception as error:
            result = {'ok': False, 'checked_at': time.time(), 'error_type': type(error).__name__}
        output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result), flush=True)
        if result['ok']:
            return
        if time.monotonic() >= deadline:
            raise SystemExit(1)
        await asyncio.sleep(30)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait-seconds', type=int, default=0)
    asyncio.run(main(parser.parse_args()))
