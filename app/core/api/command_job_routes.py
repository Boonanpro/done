"""Wake a durable voice job on its Core owner, without waiting for a poll cycle."""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from app.services import browser_lifecycle

router = APIRouter()

class Wake(BaseModel):
    job_id: str

@router.post('/internal/command-jobs/wake')
async def wake(body: Wake, request: Request):
    if (not request.client or request.client.host not in {'127.0.0.1','::1'} or request.headers.get('origin')
        or not browser_lifecycle.authorized(request.headers.get('x-dan-browser-token',''))):
        raise HTTPException(403,'Local authentication required')
    import asyncio
    from app.services.chat_service import ChatService
    from app.services.followups import decode_watch_row
    from app.services.command_job_runner import dispatch
    from app.services import command_job_state as state
    saved = state.read(body.job_id)
    if saved and saved.get('queue_owner') == 'core':
        if saved['state'] in state.TERMINAL:
            return {'accepted':bool(saved.get('accepted_at')), 'state':saved['state']}
        def accept(s):
            if s['state'] not in state.TERMINAL:
                s.setdefault('accepted_at',state.now())
        saved = state.change(body.job_id,accept)
        if saved['state'] in state.TERMINAL:
            return {'accepted':bool(saved.get('accepted_at')), 'state':saved['state']}
        dispatch({'id':saved['id'],'user_id':saved['user_id'],'room_id':saved['room_id'],
            'spec':{key:saved[key] for key in ('origin_room_id','origin_project_id','task')}})
        return {'accepted':True}
    sb=ChatService().supabase
    candidate=await asyncio.to_thread(lambda:sb.table('pending_followups').select('*').eq('id',body.job_id).execute())
    if not candidate.data:return {'accepted':False}
    if decode_watch_row(candidate.data[0])['spec'].get('engine')!='steerable_cli':
        raise HTTPException(400,'Not a voice job')
    result=await asyncio.to_thread(lambda:sb.table('pending_followups').update({'status':'firing'})
        .eq('id',body.job_id).eq('status','pending').execute())
    if not result.data:return {'accepted':False}
    row=decode_watch_row(result.data[0])
    if row['spec'].get('engine')!='steerable_cli':raise HTTPException(400,'Not a voice job')
    dispatch(row)
    return {'accepted':True}
