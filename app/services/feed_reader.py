"""One look at a page of the user's (an SNS's notifications or messages), in Dan's own browser with the saved logins:
run by feeds.py as `python -m app.services.feed_reader <url>` with DAN_BROWSER_ROOM set to the feed's browser room.
Prints one JSON line: {ok, text, open}. The browser is closed afterwards (nothing held between looks)."""
import asyncio
import json
import sys


async def main(url):
    from app.agent.v2.tools import _execute_browser_tool
    opened = await _execute_browser_tool('open_target', {'url': url})
    text, ok = '', False
    try:
        await asyncio.sleep(4)   # the page's own scripts fill the list after load
        read = await _execute_browser_tool('read', {'max_chars': 8000})
        ok = bool(read.get('success'))
        text = '\n'.join(c.get('text', '') for c in (read.get('content') or []) if isinstance(c, dict) and c.get('type') == 'text')
    finally:
        try:
            await _execute_browser_tool('close', {})
        except Exception:
            pass
    keep = ('success', 'error', 'logged_in', 'replayed_login', 'login_rejected')
    print(json.dumps({'ok': ok, 'text': text, 'open': {k: opened.get(k) for k in keep if isinstance(opened, dict)}}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1]))
