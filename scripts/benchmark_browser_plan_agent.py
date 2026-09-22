"""Real Astra/app-server + isolated production browser actions; no simulated thinking."""
import argparse
import asyncio
import copy
import json
import os
from pathlib import Path
import re
import sys
import time
from unittest.mock import AsyncMock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from playwright.async_api import async_playwright
from app.agent.v2.tools import BROWSER_TOOL, _execute_browser_tool
from app.services.browser_plan import run as run_plan, TOOL as PLAN_TOOL
from app.services.browser_flow import run as run_flow, TOOL as FLOW_TOOL
from app.services.jev_decisions import Decisions
from app.services.editor_codex import CodexTurn
from scripts.benchmark_browser_plan import PageAdapter, FLOW

ADAPTIVE='''<h1>宿泊候補の絞り込み</h1><p id="stage">Step 0</p><p id="preference"></p><div id="choices"></div>
<script>
window.count=0;window.wrong=0;
const labels=['駅近','朝食付き','低価格','禁煙','Wi-Fiあり','個室'];
const wishes=['安く泊まれる宿を探しています','朝ごはんをホテルで食べたいです','電車を降りてすぐ着く場所が希望です','タバコの煙がない部屋が希望です','部屋でインターネットを使いたいです','他の宿泊者と同室になりたくありません'];
const answers=[2,1,0,3,4,5];
document.querySelector('#preference').textContent='今回の希望: '+wishes[0];
labels.forEach((label,i)=>{const b=document.createElement('button');b.textContent=label;
b.onclick=()=>{if(window.count>=6)return;if(i!==answers[window.count]){window.wrong++;return;}
window.count++;document.querySelector('#stage').textContent='Step '+window.count;
document.querySelector('#preference').textContent=window.count<6?'今回の希望: '+wishes[window.count]:'全条件を確認しました';};
document.querySelector('#choices').append(b);});
</script>'''

def content_items(result):
    items=[]
    for c in result.get('content',[]):
        if c.get('type')=='image':
            src=c['source'];items.append({'type':'inputImage','imageUrl':'data:'+src['media_type']+';base64,'+src['data']})
        elif c.get('type')=='text':items.append({'type':'inputText','text':c['text']})
    meta={k:v for k,v in result.items() if k!='content'}
    items.append({'type':'inputText','text':json.dumps(meta,ensure_ascii=False)})
    return items

async def trial(page, mode, user_id=None, scenario='known'):
    await page.set_content(ADAPTIVE if scenario=='adaptive' else FLOW)
    await page.evaluate('window.count=0;window.wrong=0')
    proxy=PageAdapter(page)
    config_path=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'config.toml'
    servers=re.findall(r'^\[mcp_servers\.([^\].]+)\]',config_path.read_text(encoding='utf-8'),re.M) if config_path.exists() else []
    allowed={'screenshot','click','wait_for'}
    schema=copy.deepcopy(BROWSER_TOOL['input_schema'])
    schema['properties']['action']['enum']=sorted(allowed)
    keep={'action','ref','expect','observation'}
    schema['properties']={k:v for k,v in schema['properties'].items() if k in keep}
    description='Operate the isolated fixture browser; use actual observed refs or labels and verify results. click supports expect to avoid fixed waits; observation=dom avoids redundant images.'
    tools=[{'type':'function','name':'fixture_browser','description':description,'parameters':schema}]
    if mode=='plan':tools.append({'type':'function','name':'browser_plan','description':PLAN_TOOL['description'],'parameters':PLAN_TOOL['input_schema']})
    if mode=='flow':tools.append({'type':'function','name':'browser_flow','description':FLOW_TOOL['description'],'parameters':FLOW_TOOL['input_schema']})
    owner=None;events=[];assistant_messages=0
    with patch('app.tools.browser.get_executor_page',AsyncMock(return_value=proxy)),patch('app.tools.browser._browser_room_id',lambda:''),patch.dict(os.environ,{'DAN_COMMAND_JOB_ID':''}):
        initial=await _execute_browser_tool('screenshot',{})
        observation='\n'.join(c.get('text','') for c in initial['content'] if c.get('type')=='text')
        task='隔離ブラウザの検証です。「次へ」を6回押し、段階表示がStep 6になったことを確認してください。戻る・ヘルプは押さない。最終結果を短く報告。画面は開いてあります。DOMを検査した結果、段階表示のselectorは #stage、初期のtextは Step 0、各クリックで1増えます。既知の連続操作はまとめて構いません。\n'+observation
        if scenario=='adaptive':
            task='隔離ブラウザの宿泊候補の絞り込みです。各段階に表示される「今回の希望」に最も合うボタンを1つ選んでください。選択後に次の希望が表示されます。6段階すべて進めてStep 6を確認し、短く報告してください。予約や購入はありません。全段階で同じ6個のボタンが候補ですが、次の希望は進めるまで分かりません。段階表示のselectorは #stage、最終textは Step 6。\n'+observation
            task+='\n実DOMで観測した今回の希望のselectorは #preference です。'
        started=time.perf_counter()
        try:
            owner=CodexTurn()
            await owner.start([{'role':'user','content':task}],tools,
                'Complete the user task using the supplied fixture_browser'+(' and browser_plan' if mode=='plan' else ' and browser_flow' if mode=='flow' else '')+'. All browser actions are isolated. Do not use shell, web, filesystem, other tools or external services. Preserve correctness and use the fastest supported verified path. Images are available from screenshot; never claim unobserved success.',
                'gpt-6-astra',config_overrides={'features.shell_tool':False,'mcp_servers':{n.strip('"'):{'enabled':False} for n in servers}})
            while True:
                event=await owner.receive()
                method,params=event.get('method'),event.get('params',{})
                if method=='item/tool/call':
                    arguments=params.get('arguments',{})
                    if isinstance(arguments,str):arguments=json.loads(arguments)
                    action=arguments.get('action')
                    t=time.perf_counter()
                    name=params.get('tool',params.get('name'))
                    if mode=='plan' and name=='browser_plan':
                        action='run_plan'
                        try:result=await run_plan(arguments)
                        except Exception as e:result={'success':False,'error':type(e).__name__+':'+str(e)}
                    elif mode=='flow' and name=='browser_flow':
                        action='run_flow'
                        try:result=await run_flow(arguments,user_id=user_id)
                        except Exception as e:result={'success':False,'error':type(e).__name__+':'+str(e)}
                    elif name!='fixture_browser' or action not in allowed or set(arguments)-keep:
                        result={'success':False,'error':'Unsupported fixture action'}
                    else:
                        result=await _execute_browser_tool(action,arguments)
                    # Only synthetic fixture inputs exist in this runner.
                    events.append({'action':action,'elapsed_ms':round((time.perf_counter()-t)*1000,2),'success':bool(result.get('success')),
                                   'arguments':arguments,'error':result.get('error'),'reason':result.get('reason')})
                    owner.send({'id':event['id'],'result':{'success':bool(result.get('success')),'contentItems':content_items(result)}})
                elif method=='item/completed' and params.get('item',{}).get('type')=='agentMessage':
                    assistant_messages+=1
                elif method=='turn/completed':
                    status=params['turn']['status']
                    break
                elif method=='process/closed':raise RuntimeError('CLI closed')
                elif 'id' in event and method:
                    owner.send({'id':event['id'],'error':{'code':-32601,'message':'Only fixture_browser is available'}})
            return {'mode':mode,'scenario':scenario,'wall_ms':round((time.perf_counter()-started)*1000,2),'status':status,
                'verified':await page.evaluate('window.count===6 && window.wrong===0'),
                'tool_calls':len(events),'assistant_messages':assistant_messages,'tools':events}
        finally:
            if owner:owner.close()

async def main(args):
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    os.environ['DAN_BROWSER_TIMING_LOG']=str(out.with_suffix('.timing.jsonl'))
    results=[]
    original_choose=Decisions.choose
    async def bounded_choose(self,state,questions):
        from scripts.jev_trial_budget import reserve
        if not args.live or not reserve(state,questions):
            return {'available':False,'reason':'evaluation_call_cap'}
        return await original_choose(self,state,questions)
    # Explicit opt-in; the shared ledger bounds all paid evaluation scripts.
    with patch.dict(os.environ,{'DAN_JEV_BROWSER_ENABLED':'1' if args.live else '0'}),patch.object(Decisions,'choose',bounded_choose):
        await run_trials(args,out,results)

async def run_trials(args,out,results):
    async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        try:
            for i in range(args.rounds):
                comparison='flow' if args.live else 'plan'
                for mode in ([args.mode] if args.mode else (['existing',comparison] if i%2==0 else [comparison,'existing'])):
                    page=await browser.new_page()
                    row=await asyncio.wait_for(trial(page,mode,args.user_id,args.scenario),timeout=180)
                    results.append(row);print(json.dumps(row),flush=True)
                    await page.screenshot(path=str(out.with_name(f'{out.stem}-{i}-{mode}.png')))
                    await page.close()
                    out.write_text(json.dumps({'scope':'Real Astra high reasoning, isolated preopened fixture, dynamic tools; includes CLI startup, model and actions. Not production chat.','rows':results},indent=2),encoding='utf-8')
        finally:await browser.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds',type=int,default=2)
    parser.add_argument('--mode',choices=['existing','plan','flow'])
    parser.add_argument('--live',action='store_true',help='Use paid Jev API; requires prior spending authorization')
    parser.add_argument('--user-id')
    parser.add_argument('--scenario',choices=['known','adaptive'],default='known')
    parser.add_argument('--output',default='scratch/jev-speed-audit-20260917/astra-benchmark.json')
    args=parser.parse_args()
    if args.live and not args.user_id:parser.error('--live requires --user-id')
    if args.mode=='flow' and not args.live:parser.error('--mode flow requires explicit --live')
    if not 1<=args.rounds<=10:parser.error('--rounds must be 1..10')
    asyncio.run(main(args))
