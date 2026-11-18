"""The /script-listen screen: hear a talk script from its Google Doc and fix a sentence on the spot
(app/services/script_listen.py)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.chat_routes import TokenData, get_current_user
from app.services import script_listen as S

router = APIRouter(prefix='/script-listen', tags=['script-listen'])


def _fail(exc):
    if isinstance(exc, S.ListenError):
        raise HTTPException(status_code=exc.status, detail=str(exc))
    raise exc


@router.get('/doc/{doc_id}')
async def get_doc(doc_id: str, voice: str = S.DEFAULT_VOICE, user: TokenData = Depends(get_current_user)):
    try: return await run_in_threadpool(S.read, S.doc_id_from(doc_id), voice)
    except Exception as exc: _fail(exc)


@router.get('/doc/{doc_id}/version')
async def get_version(doc_id: str, user: TokenData = Depends(get_current_user)):
    return {'version': await run_in_threadpool(S.version, S.doc_id_from(doc_id))}


class Ahead(BaseModel):
    voice: str = S.DEFAULT_VOICE
    items: list[dict]          # [{speak, gap}] in listening order, from the listener's place


@router.post('/ahead')
async def ahead(body: Ahead, user: TokenData = Depends(get_current_user)):
    items = [(S.clip_key(i['speak'], body.voice, i.get('gap', 's')), i['speak'], body.voice, i.get('gap', 's'))
             for i in body.items[:2000] if i.get('speak') and i.get('gap', 's') in S.GAPS]
    return {'queued': S.prepare(items)}


@router.get('/clip/{key}.mp3')
async def clip(key: str, t: str = Query(..., max_length=2000), v: str = S.DEFAULT_VOICE, g: str = 's',
               user: TokenData = Depends(get_current_user)):
    if g not in S.GAPS or S.clip_key(t, v, g) != key:
        raise HTTPException(status_code=400, detail='音声の指定が正しくありません。')
    try: await run_in_threadpool(S.synthesize, t, v, g)
    except Exception as exc: _fail(exc)
    return FileResponse(S.clip_path(key), media_type='audio/mpeg',
                        headers={'Cache-Control': 'private, max-age=31536000, immutable'})


class Edit(BaseModel):
    old: str
    new: str
    start: int | None = None


@router.post('/doc/{doc_id}/edit')
async def edit(doc_id: str, body: Edit, user: TokenData = Depends(get_current_user)):
    try: return await run_in_threadpool(S.edit, S.doc_id_from(doc_id), body.old, body.new, None, body.start)
    except Exception as exc: _fail(exc)
