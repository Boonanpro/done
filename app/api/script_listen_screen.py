"""The /script-listen screen: hear a talk script from its Google Doc and fix a sentence on the spot
(app/services/script_listen.py)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

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


class Replace(BaseModel):
    para_from: int
    para_to: int
    old: str = Field(max_length=200_000)
    new: str = Field(max_length=200_000)
    old_bmask: str = Field('', max_length=200_000)
    new_bmask: str = Field('', max_length=200_000)
    mode: str = 'edit'          # edit: into the doc / suggest: the owner's suggestion (kept by the screen)


@router.post('/doc/{doc_id}/replace')
async def replace(doc_id: str, body: Replace, user: TokenData = Depends(get_current_user)):
    try:
        return await run_in_threadpool(S.replace, S.doc_id_from(doc_id), body.para_from, body.para_to, body.old, body.new,
                                       body.old_bmask, body.new_bmask, body.mode)
    except Exception as exc: _fail(exc)


class Decide(BaseModel):
    id: str
    accept: bool


@router.post('/doc/{doc_id}/suggestion')
async def decide(doc_id: str, body: Decide, user: TokenData = Depends(get_current_user)):
    try: return await run_in_threadpool(S.decide, S.doc_id_from(doc_id), body.id, body.accept)
    except Exception as exc: _fail(exc)


@router.post('/doc/{doc_id}/suggestions/accept-all')
async def accept_all(doc_id: str, user: TokenData = Depends(get_current_user)):
    try: return await run_in_threadpool(S.accept_all, S.doc_id_from(doc_id))
    except Exception as exc: _fail(exc)


@router.get('/doc/{doc_id}/comments')
async def get_comments(doc_id: str, user: TokenData = Depends(get_current_user)):
    try: return await run_in_threadpool(S.comments, S.doc_id_from(doc_id))
    except Exception as exc: _fail(exc)


class NewComment(BaseModel):
    text: str
    quote: str = ''
    start: int | None = None
    sentence: str = ''
    suggestion: dict | None = None      # {id, ins, del}: written on a suggestion's card


@router.post('/doc/{doc_id}/comments')
async def add_comment(doc_id: str, body: NewComment, user: TokenData = Depends(get_current_user)):
    try: return await run_in_threadpool(S.add_comment, S.doc_id_from(doc_id), body.quote, body.text, body.start, body.sentence,
                                       body.suggestion)
    except Exception as exc: _fail(exc)


class Reply(BaseModel):
    text: str
    suggestion: dict | None = None


@router.post('/doc/{doc_id}/comments/{comment_id}/reply')
async def reply(doc_id: str, comment_id: str, body: Reply, user: TokenData = Depends(get_current_user)):
    try: return await run_in_threadpool(S.reply, S.doc_id_from(doc_id), comment_id, body.text, body.suggestion)
    except Exception as exc: _fail(exc)


class Settle(BaseModel):
    reopen: bool = False


@router.post('/doc/{doc_id}/comments/{comment_id}/settle')
async def settle(doc_id: str, comment_id: str, body: Settle, user: TokenData = Depends(get_current_user)):
    try: return await run_in_threadpool(S.settle, S.doc_id_from(doc_id), comment_id, body.reopen)
    except Exception as exc: _fail(exc)
