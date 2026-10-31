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


def screen_image(contents, tool, arguments):
    """Persist only a tool's real screen, behind the call room's authentication."""
    if tool not in ('browser','browser_plan','browser_flow','phone'): return ''
    import base64, re
    from pathlib import Path
    from app.services.voice_screen_media import store
    room = os.environ.get('DAN_SESSION_ID','')
    for block in reversed(contents):
        if getattr(block,'type','') == 'image':
            return store(room,base64.b64decode(block.data,validate=True),getattr(block,'mimeType',''))
    # phone's screenshot tool returns a local file, not an MCP image block.
    if tool == 'phone' and arguments.get('action') == 'screenshot':
        from app.paths import DONE_ROOT
        allowed = (DONE_ROOT/'uploads').resolve()
        for block in contents:
            match = re.search(r'スクリーンショット: (.+?\.png)（画像として読む）', getattr(block,'text',''))
            if not match: continue
            source = Path(match[1]).resolve()
            if source.parent == allowed and re.fullmatch(r'phone-\d+\.png',source.name):
                return store(room,source.read_bytes(),'image/png')
    return ''


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
                try: image = screen_image(contents, str(req.get('name') or ''), req.get('arguments') or {})
                except (OSError,ValueError): image = ''
                reply = {'text': ('\n'.join(texts)[:OUTPUT_CHARS] or '（出力なし）'), 'stage_image': image}
                if str(req.get('name') or '') in ('browser','browser_plan','browser_flow') and image:
                    try:
                        from app.tools.browser import _send_executor_command
                        reply['stage_stream'] = await asyncio.to_thread(_send_executor_command, 'voice_stream_url')
                    except Exception:
                        pass
        except Exception as exc:
            reply = {'text': f'操作結果が不明です。再送せず現在の画面を確かめてください: {type(exc).__name__}: {str(exc)[:300]}'}
        out.write(json.dumps({'id': rid, **reply}, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
