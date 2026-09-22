"""Read-only real prompt assembly with an isolated, non-secret MCP config.

Does not start a model or browser, send a message, or save prompt contents.
"""
import asyncio,json,os,statistics,sys,time,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.agent import cli_runner as runner
from app.services.owner import resolve_owner_user_id

async def main():
    room='speed-preparation-'+uuid.uuid4().hex
    user=resolve_owner_user_id()
    kwargs=dict(title='',description='',status='in_progress',latest_user_message='準備処理の速度検証',room_id=room,user_id=user)
    rows=[]
    async def measure(mode):
        ticks=[];finished=False;started=time.perf_counter()
        async def heartbeat():
            while not finished:
                await asyncio.sleep(.01);ticks.append(time.perf_counter())
        pulse=asyncio.create_task(heartbeat());await asyncio.sleep(0)
        try:
            if mode=='before':result=[runner._build_system_prompt(**kwargs),runner._build_mcp_config(room,user,None)]
            else:result=await runner._prepare_cli_inputs(room,user,None,None,None,kwargs)
            elapsed=(time.perf_counter()-started)*1000
            return_value={'mode':mode,'preparation_ms':round(elapsed,2),'prompt_chars':len(result[0]),
                          'current_browser_guidance':'browser_flow' in result[0]}
        finally:
            finished=True;await pulse
            runner._cleanup_mcp_config(room)
        gaps=[ticks[0]-started]+[b-a for a,b in zip(ticks,ticks[1:])]
        return_value['max_heartbeat_gap_ms']=round(max(gaps)*1000,2)
        return return_value
    with patch.dict(os.environ,{'ENCRYPTION_KEY':'synthetic-not-a-secret'}):
        for i in range(5):
            for mode in (['before','after'] if i%2==0 else ['after','before']):
                rows.append(await measure(mode))
    summary={m:{k:statistics.median(r[k] for r in rows if r['mode']==m) for k in ('preparation_ms','max_heartbeat_gap_ms')} for m in ('before','after')}
    path=Path('scratch/jev-speed-audit-20260917/preparation-real.json')
    path.write_text(json.dumps({'scope':'Actual current prompt assembly, read-only database, synthetic unused room, non-secret MCP config; no model.','summary':summary,'rows':rows},indent=2),encoding='utf-8')
    print(json.dumps(summary))

if __name__=='__main__':asyncio.run(main())
