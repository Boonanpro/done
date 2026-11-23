"""The 「動画の編集」 view of the instructions screen: the stages of editing a video, what Dan reads and runs at each,
past work replayed stage by stage, and Dan's proposed changes the owner approves or rejects (app/services/video_flow.py)."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.chat_routes import get_current_user
from app.services import video_flow
from app.services.owner import resolve_owner_user_id

router = APIRouter(prefix='/video-flow')


async def owner(user=Depends(get_current_user)):
    if user.user_id != await asyncio.to_thread(resolve_owner_user_id):
        raise HTTPException(403, '本人の画面から開いてください。')
    return user.user_id


@router.get('')
async def overview(case: str = '', _=Depends(owner)):
    return await asyncio.to_thread(video_flow.overview, case)


class DecideBody(BaseModel):
    decision: str
    note: str = ''


@router.post('/proposals/{proposal_id}')
async def decide(proposal_id: str, body: DecideBody, _=Depends(owner)):
    try:
        return await asyncio.to_thread(video_flow.decide, proposal_id, body.decision, body.note)
    except KeyError: raise HTTPException(404, 'その案はありません。')
    except ValueError as exc: raise HTTPException(422, str(exc))
    except RuntimeError as exc: raise HTTPException(409, str(exc))
