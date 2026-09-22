"""Exercise the deployed MCP and Core-owned browser on a new synthetic profile.

No user sites, messages, input data or authenticated profiles are touched.
Uses the approved runtime budget. Always closes only its own test browser.
"""
import asyncio,json,os,sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from playwright.async_api import async_playwright
from app.services.owner import resolve_owner_user_id
from app.services.browser_lifecycle import request_session
from scripts.benchmark_browser_plan_agent import ADAPTIVE

async def main():
    root=Path(__file__).resolve().parents[1]
    proof=root/'scratch/jev-speed-audit-20260917'
    fixture=proof/'live-fixture.html';fixture.write_text('<meta charset="utf-8">'+ADAPTIVE,encoding='utf-8')
    room='jev-live-proof-'+uuid.uuid4().hex
    env={**os.environ,'DAN_SESSION_ID':room,'DAN_USER_ID':resolve_owner_user_id(),'DAN_CORE_PORT':'9000','DAN_COMMAND_JOB_ID':''}
    env.pop('DAN_JEV_BROWSER_ENABLED',None)
    outcome={'room':room,'scope':'Production MCP/Core; isolated synthetic profile; actual Jev; no Astra.'}
    try:
        async with stdio_client(StdioServerParameters(command=sys.executable,args=[str(root/'app/mcp_server.py')],env=env)) as (reader,writer):
            async with ClientSession(reader,writer) as session:
                await session.initialize()
                tools=(await session.list_tools()).tools
                outcome['flow_discovered']='browser_flow' in {t.name for t in tools}
                assert outcome['flow_discovered'],'Budget publication not enabled'
                await session.call_tool('browser',{'action':'open_target','url':fixture.as_uri(),'ready':{'selector':'#stage','text':'Step 0'},'observation':'dom'})
                started=time.perf_counter()
                response=await session.call_tool('browser_flow',{'expected_url':fixture.as_uri(),
                    'goal':'各段階に表示される今回の希望に最も合うボタンを選び、6段階進む。','instruction_selector':'#preference',
                    'candidates':[{'role':'button','name':s} for s in ['駅近','朝食付き','低価格','禁煙','Wi-Fiあり','個室']],
                    'until':{'selector':'#stage','text':'Step 6'},'max_steps':6})
                outcome['wall_ms']=round((time.perf_counter()-started)*1000,2)
                for part in response.content:
                    if getattr(part,'type',None)=='text' and 'Browser flow result: ' in part.text:
                        data=part.text.split('Browser flow result: ',1)[1]
                        outcome['result']=json.JSONDecoder().raw_decode(data)[0]
                status=await asyncio.to_thread(request_session,'status',room)
                assert status['owner']=='dan-core' and status['alive']
                async with async_playwright() as pw:
                    browser=await pw.chromium.connect_over_cdp('http://127.0.0.1:'+str(status['port']))
                    page=next(p for c in browser.contexts for p in c.pages if p.url==fixture.as_uri())
                    outcome['verified']=await page.evaluate('window.count===6 && window.wrong===0 && document.querySelector("#stage").textContent==="Step 6"')
                    outcome['observed_instruction']=await page.locator('#preference').inner_text()
                    outcome['wrong_clicks']=await page.evaluate('window.wrong')
                    await page.screenshot(path=str(proof/'live-fixture.png'))
    finally:
        closed=await asyncio.to_thread(request_session,'close',room)
        outcome['test_browser_closed']=not closed['alive']
        (proof/'live-proof.json').write_text(json.dumps(outcome,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(outcome,ensure_ascii=False))
    assert outcome.get('verified') and outcome.get('result',{}).get('success')

if __name__=='__main__':asyncio.run(main())
