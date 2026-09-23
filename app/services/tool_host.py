"""A voice call's hands: Dan's whole tool set in its own process, for the voice backend (voice_tools talks to it).

Dan's tools read the owner, the room and the browser from the process environment when they are imported (mcp_server,
the browser executor), so they cannot run inside the shared sandbox process for one call's owner. This process is
started per owner and room with that environment, and runs the tools exactly as a job does.

Protocol: one JSON object per line on stdin ({"id", "op": "catalog"|"help"|"call", "name", "arguments"}), one JSON object
per line on the original stdout ({"id", "text", "images"}). Everything the tools print goes to stderr.

Usage: python -m app.services.tool_host   (environment: DAN_USER_ID, DAN_SESSION_ID, DAN_BROWSER_ROOM, DAN_TOOL_HOST=1)
"""
import asyncio
import json
import os
import sys

OUTPUT_CHARS = 12000


def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    out = os.fdopen(os.dup(sys.stdout.fileno()), 'w', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr   # the tools' prints must not corrupt the answers
    from app.mcp_server import _ensure_env_from_dotenv
    _ensure_env_from_dotenv()
    asyncio.run(serve(out))


async def serve(out):
    from app.mcp_server import list_tools, call_tool
    from app.services import dan_tools
    mcp = await list_tools()
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            return
        try:
            req = json.loads(line)
        except ValueError:
            continue
        rid, op = req.get('id'), req.get('op')
        try:
            if op == 'catalog':
                reply = {'text': dan_tools.catalog(mcp, native=req.get('native') or [])}
            elif op == 'help':
                reply = {'text': dan_tools.help_text(mcp, str(req.get('name') or ''))}
            else:
                contents = await call_tool(str(req.get('name') or ''), req.get('arguments') or {})
                texts = [c.text for c in contents if getattr(c, 'type', '') == 'text']
                images = sum(1 for c in contents if getattr(c, 'type', '') == 'image')
                reply = {'text': ('\n'.join(texts)[:OUTPUT_CHARS] or '（出力なし）') + (f'\n（画像{images}枚は声の通話では見られない）' if images else '')}
        except Exception as exc:
            reply = {'text': f'操作は実行していません: {type(exc).__name__}: {str(exc)[:300]}'}
        out.write(json.dumps({'id': rid, **reply}, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
