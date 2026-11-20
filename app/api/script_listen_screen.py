"""The /script-listen screen: hear a talk script from its Google Doc and fix a sentence on the spot
(app/services/script_listen.py)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.chat_routes import TokenData, get_current_user
from app.services import script_listen as S
from app.services import script_listen_refs as R

router = APIRouter(prefix='/script-listen', tags=['script-listen'])


def _followed(doc_id, result):
    """The working doc changed from the screen: its customer's copy follows a few seconds later (script_share)."""
    try:
        from app.services import script_share
        script_share.poke(S.doc_id_from(doc_id))
    except Exception:
        import logging
        logging.exception('customer copy follow failed')
    return result


def _fail(exc):
    if isinstance(exc, S.ListenError):
        raise HTTPException(status_code=exc.status, detail=str(exc))
    raise exc


@router.get('/doc/{doc_id}')
async def get_doc(doc_id: str, voice: str = S.DEFAULT_VOICE, user: TokenData = Depends(get_current_user)):
    try: return await run_in_threadpool(S.read, S.doc_id_from(doc_id), voice)
    except Exception as exc: _fail(exc)


@router.get('/doc/{doc_id}/references')
async def get_references(doc_id: str, user: TokenData = Depends(get_current_user)):
    """The scripts of the videos this script was modelled on (app/services/script_listen_refs.py)."""
    try: return await run_in_threadpool(R.read, S.doc_id_from(doc_id))
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc))


@router.get('/doc/{doc_id}/version')
async def get_version(doc_id: str, user: TokenData = Depends(get_current_user)):
    try:
        from app.services import script_share
        script_share.maybe_check(S.doc_id_from(doc_id))   # what the other side did in their copy comes in too
    except Exception:
        pass
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
    try: return _followed(doc_id, await run_in_threadpool(S.edit, S.doc_id_from(doc_id), body.old, body.new, None, body.start))
    except Exception as exc: _fail(exc)


class Replace(BaseModel):
    para_from: int
    para_to: int
    old: str = Field(max_length=200_000)
    new: str = Field(max_length=200_000)
    old_bmask: str = Field('', max_length=200_000)
    new_bmask: str = Field('', max_length=200_000)
    mode: str = 'edit'          # edit: into the doc / suggest: the owner's suggestion (kept by the screen)
    new_dmask: str = Field('', max_length=200_000)   # suggest: letters struck on the screen (still in new)


@router.post('/doc/{doc_id}/replace')
async def replace(doc_id: str, body: Replace, user: TokenData = Depends(get_current_user)):
    try:
        return _followed(doc_id, await run_in_threadpool(S.replace, S.doc_id_from(doc_id), body.para_from, body.para_to, body.old, body.new,
                                       body.old_bmask, body.new_bmask, body.mode, body.new_dmask))
    except Exception as exc: _fail(exc)


class Decide(BaseModel):
    id: str
    accept: bool


@router.post('/doc/{doc_id}/suggestion')
async def decide(doc_id: str, body: Decide, user: TokenData = Depends(get_current_user)):
    try: return _followed(doc_id, await run_in_threadpool(S.decide, S.doc_id_from(doc_id), body.id, body.accept))
    except Exception as exc: _fail(exc)


@router.post('/doc/{doc_id}/suggestions/accept-all')
async def accept_all(doc_id: str, user: TokenData = Depends(get_current_user)):
    try: return _followed(doc_id, await run_in_threadpool(S.accept_all, S.doc_id_from(doc_id)))
    except Exception as exc: _fail(exc)


@router.post('/doc/{doc_id}/suggestions/reject-all')
async def reject_all(doc_id: str, user: TokenData = Depends(get_current_user)):
    try: return _followed(doc_id, await run_in_threadpool(S.reject_all, S.doc_id_from(doc_id)))
    except Exception as exc: _fail(exc)


@router.get('/doc/{doc_id}/comments')
async def get_comments(doc_id: str, user: TokenData = Depends(get_current_user)):
    try: return await run_in_threadpool(S.comments, S.doc_id_from(doc_id))
    except Exception as exc: _fail(exc)


@router.get('/doc/{doc_id}/activity')
async def get_activity(doc_id: str, user: TokenData = Depends(get_current_user)):
    """Dan's answers to the doc's comments that are going on now (or just ended), with their work log."""
    try: return await run_in_threadpool(S.activity, S.doc_id_from(doc_id))
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


class NewImage(BaseModel):
    after_para: int
    type: str = Field(max_length=100)
    data: str = Field(max_length=28_000_000)    # base64 (20 MB at most)


@router.post('/doc/{doc_id}/image')
async def add_image(doc_id: str, body: NewImage, user: TokenData = Depends(get_current_user)):
    import base64
    import binascii
    try: data = base64.b64decode(body.data.split(',')[-1], validate=True)
    except (binascii.Error, ValueError): raise HTTPException(status_code=400, detail='画像を読めませんでした。')
    try: return await run_in_threadpool(S.add_image, S.doc_id_from(doc_id), body.after_para, data, body.type)
    except Exception as exc: _fail(exc)


class DropImage(BaseModel):
    id: str = Field(max_length=200)


@router.post('/doc/{doc_id}/image/delete')
async def remove_image(doc_id: str, body: DropImage, user: TokenData = Depends(get_current_user)):
    try: return await run_in_threadpool(S.remove_image, S.doc_id_from(doc_id), body.id)
    except Exception as exc: _fail(exc)


# ── サムネ（上の部分の絵）を部品で直す（app/services/script_listen_thumbs.py）──

class ThumbOpen(BaseModel):
    object: str | None = Field(None, max_length=200)
    order: int | None = None


@router.post('/doc/{doc_id}/thumb/open')
async def thumb_open(doc_id: str, body: ThumbOpen, user: TokenData = Depends(get_current_user)):
    from app.services import script_listen_thumbs as T
    try: return await run_in_threadpool(T.open_work, S.doc_id_from(doc_id), body.object, body.order)
    except Exception as exc: _fail(exc)


@router.get('/doc/{doc_id}/thumbs')
async def thumbs(doc_id: str, user: TokenData = Depends(get_current_user)):
    """The doc's thumbnail works; a work changed since its picture was made is put into the doc in the background."""
    from app.services import script_listen_thumbs as T
    d = S.doc_id_from(doc_id)
    items = await run_in_threadpool(T.status, d)
    if any(i['stale'] for i in items):
        await run_in_threadpool(T.sync_soon, d)
    return {'items': items}


class ThumbSync(BaseModel):
    content_id: str | None = Field(None, max_length=100)


@router.post('/doc/{doc_id}/thumb/sync')
async def thumb_sync(doc_id: str, body: ThumbSync, user: TokenData = Depends(get_current_user)):
    from app.services import script_listen_thumbs as T
    try: return await run_in_threadpool(T.sync, S.doc_id_from(doc_id), body.content_id)
    except Exception as exc: _fail(exc)


# ── 右の「ダンと台本」の会話（app/services/script_rooms.py）──

@router.post('/doc/{doc_id}/room')
async def chat_room(doc_id: str, user: TokenData = Depends(get_current_user)):
    from app.services import script_rooms
    try: return await script_rooms.ensure_room(user.user_id, S.doc_id_from(doc_id))
    except Exception as exc: _fail(exc)


class ScreenState(BaseModel):
    para: int | None = None
    sentence: str = Field('', max_length=2000)
    selection: str = Field('', max_length=4000)
    playing: bool = False
    thumb: str = Field('', max_length=200)


@router.post('/doc/{doc_id}/state')
async def screen_state(doc_id: str, body: ScreenState, user: TokenData = Depends(get_current_user)):
    """Where the owner is on the screen, for the chat's 「ここ」."""
    from app.services import script_rooms
    await run_in_threadpool(script_rooms.put_state, S.doc_id_from(doc_id), body.model_dump())
    return {'ok': True}


# ── 相手に送る共有用のリンク（app/services/script_share.py）──

@router.get('/doc/{doc_id}/share')
async def share_state(doc_id: str, user: TokenData = Depends(get_current_user)):
    from app.services import script_share
    try: return await run_in_threadpool(script_share.state, S.doc_id_from(doc_id))
    except Exception as exc: _fail(exc)


class ShareBody(BaseModel):
    update: bool = False


@router.post('/doc/{doc_id}/share')
async def share(doc_id: str, body: ShareBody, user: TokenData = Depends(get_current_user)):
    from app.services import script_share
    try: return await run_in_threadpool(script_share.share, S.doc_id_from(doc_id), body.update)
    except Exception as exc: _fail(exc)
