"""
Studio API Routes - AI Vlog Production Dashboard
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List

from app.api.chat_routes import get_current_user, TokenData
from app.services.studio_service import StudioService
from app.models.studio_schemas import (
    ChannelCreateRequest, ChannelUpdateRequest, ChannelResponse,
    EpisodeCreateRequest, EpisodeUpdateRequest, EpisodeResponse,
    ScriptMessageRequest, ScriptMessageResponse,
    VoiceGenerateRequest, VoiceTrackResponse,
    VideoGenerateRequest, VideoClipResponse,
)

router = APIRouter(prefix="/studio", tags=["studio"])


def get_service() -> StudioService:
    return StudioService()


# ==================== Channels ====================

@router.post("/channels", response_model=ChannelResponse)
async def create_channel(
    req: ChannelCreateRequest,
    current_user: TokenData = Depends(get_current_user),
    svc: StudioService = Depends(get_service),
):
    data = req.model_dump(exclude_none=True)
    return await svc.create_channel(current_user.user_id, data)


@router.get("/channels", response_model=List[ChannelResponse])
async def list_channels(
    current_user: TokenData = Depends(get_current_user),
    svc: StudioService = Depends(get_service),
):
    return await svc.list_channels(current_user.user_id)


@router.get("/channels/{channel_id}", response_model=ChannelResponse)
async def get_channel(
    channel_id: str,
    current_user: TokenData = Depends(get_current_user),
    svc: StudioService = Depends(get_service),
):
    channel = await svc.get_channel(channel_id, current_user.user_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@router.patch("/channels/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: str,
    req: ChannelUpdateRequest,
    current_user: TokenData = Depends(get_current_user),
    svc: StudioService = Depends(get_service),
):
    data = req.model_dump(exclude_none=True)
    return await svc.update_channel(channel_id, current_user.user_id, data)


# ==================== Episodes ====================

@router.post("/episodes", response_model=EpisodeResponse)
async def create_episode(
    req: EpisodeCreateRequest,
    current_user: TokenData = Depends(get_current_user),
    svc: StudioService = Depends(get_service),
):
    data = req.model_dump(exclude_none=True)
    return await svc.create_episode(current_user.user_id, data)


@router.get("/channels/{channel_id}/episodes", response_model=List[EpisodeResponse])
async def list_episodes(
    channel_id: str,
    current_user: TokenData = Depends(get_current_user),
    svc: StudioService = Depends(get_service),
):
    return await svc.list_episodes(channel_id, current_user.user_id)


@router.get("/episodes/{episode_id}", response_model=EpisodeResponse)
async def get_episode(
    episode_id: str,
    current_user: TokenData = Depends(get_current_user),
    svc: StudioService = Depends(get_service),
):
    episode = await svc.get_episode(episode_id, current_user.user_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    return episode


@router.patch("/episodes/{episode_id}", response_model=EpisodeResponse)
async def update_episode(
    episode_id: str,
    req: EpisodeUpdateRequest,
    current_user: TokenData = Depends(get_current_user),
    svc: StudioService = Depends(get_service),
):
    data = req.model_dump(exclude_none=True)
    return await svc.update_episode(episode_id, current_user.user_id, data)


# ==================== Script Chat ====================

@router.post("/script/chat")
async def chat_script(
    req: ScriptMessageRequest,
    current_user: TokenData = Depends(get_current_user),
    svc: StudioService = Depends(get_service),
):
    try:
        response = await svc.chat_script(req.episode_id, current_user.user_id, req.message)
        return {"response": response}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Voice ====================

@router.post("/voice/generate", response_model=VoiceTrackResponse)
async def generate_voice(
    req: VoiceGenerateRequest,
    current_user: TokenData = Depends(get_current_user),
    svc: StudioService = Depends(get_service),
):
    try:
        return await svc.generate_voice(
            req.episode_id, current_user.user_id,
            req.text, req.label or "", req.voice_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/episodes/{episode_id}/voice", response_model=List[VoiceTrackResponse])
async def list_voice_tracks(
    episode_id: str,
    current_user: TokenData = Depends(get_current_user),
    svc: StudioService = Depends(get_service),
):
    return await svc.list_voice_tracks(episode_id, current_user.user_id)


# ==================== Video ====================

@router.post("/video/generate", response_model=VideoClipResponse)
async def generate_video(
    req: VideoGenerateRequest,
    current_user: TokenData = Depends(get_current_user),
    svc: StudioService = Depends(get_service),
):
    try:
        return await svc.generate_video(
            req.episode_id, current_user.user_id,
            req.prompt, req.duration, req.mode,
            req.label or "", req.negative_prompt or "",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/video/{clip_id}/status", response_model=VideoClipResponse)
async def check_video_status(
    clip_id: str,
    current_user: TokenData = Depends(get_current_user),
    svc: StudioService = Depends(get_service),
):
    try:
        return await svc.check_video_status(clip_id, current_user.user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/episodes/{episode_id}/clips", response_model=List[VideoClipResponse])
async def list_video_clips(
    episode_id: str,
    current_user: TokenData = Depends(get_current_user),
    svc: StudioService = Depends(get_service),
):
    return await svc.list_video_clips(episode_id, current_user.user_id)
