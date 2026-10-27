"""Read-only drain proof for a generation; unknown app tasks keep it alive."""
import asyncio
from fastapi import APIRouter, Request, HTTPException
from app.services import browser_lifecycle
router = APIRouter()


@router.get('/internal/generation/activity')
async def activity(request: Request):
    if not request.client or request.client.host not in {'127.0.0.1', '::1'} or not browser_lifecycle.authorized(request.headers.get('x-dan-browser-token', '')):
        # Sandbox hasn't initialized a Core token. Use the same saved local
        # credential without changing account/browser state.
        import secrets
        try: valid = secrets.compare_digest(browser_lifecycle._token_path().read_text().strip(), request.headers.get('x-dan-browser-token', ''))
        except OSError: valid = False
        if not valid or not request.client or request.client.host not in {'127.0.0.1', '::1'}: raise HTTPException(403)
    current = asyncio.current_task()
    busy = []
    for task in asyncio.all_tasks():
        if task is current or task.done(): continue
        coro = task.get_coro()
        module = getattr(coro, '__module__', '')
        frame = getattr(coro, 'cr_frame', None)
        if frame is not None: module = frame.f_globals.get('__name__', module)
        if module.startswith('app.') and module != 'app.services.job_process':
            busy.append(module + '.' + getattr(coro, '__qualname__', 'task'))
    return {'idle': not busy, 'tasks': len(busy)}
