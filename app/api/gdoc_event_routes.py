"""Public push ingress. No OAuth tokens or comment contents reach this route."""
import asyncio
from fastapi import APIRouter, HTTPException, Request, Response
from app.services import gdoc_events

router = APIRouter(prefix='/api/v1/gdoc-events')

@router.post('/push')
async def push(request: Request):
    if not await asyncio.to_thread(gdoc_events.accept, dict(request.headers)):
        raise HTTPException(403, 'Invalid channel')
    return Response(status_code=204)
