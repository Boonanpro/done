"""Isolated real-Chromium benchmark. --live additionally uses stored Jev access.

No user site, submissions, messages, or production browser is touched.
Output contains timing, decision quality, and fixture IDs only.
"""
import argparse
import asyncio
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import statistics
import sys
import time
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.async_api import async_playwright
from app.agent.v2.tools import _execute_browser_tool
from app.services import browser_plan as plan
from app.services.jev_decisions import Decisions

# The adapter exercises the production executor in an isolated Playwright page.
spec = importlib.util.spec_from_file_location('browser_plan_tests', ROOT/'tests/test_browser_plan.py')
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
PageAdapter = helpers.PageAdapter

LABELS = ['姓','名','メールアドレス','電話番号','郵便番号','都道府県','市区町村','番地']
TARGETS = ['苗字を記入する欄','下の名前を記入する欄','連絡先の電子メールの欄','連絡先の電話番号の欄',
           '住所の郵便番号の欄','住所の都道府県の欄','住所の市区町村の欄','住所の番地の欄']

def form_args(semantic=False):
    return {'expected_url':'about:blank','steps':[{'action':'fill_form','fields':[
        {'target':target,'value':'sample-'+str(i), 'candidates':[
            {'role':'textbox','name':label} for label in (LABELS if semantic else [LABELS[i]])]}
        for i,target in enumerate(TARGETS)]}]}

FORM = ('<h1>連絡先（架空の検証フォーム）</h1>'+''.join(
    f'<label>{label}<input id="f{i}"></label><br>' for i,label in enumerate(LABELS))+
    '<button onclick="window.submissions=(window.submissions||0)+1">送信</button>')

FLOW = '''<h1>Fixture workflow</h1><p id="stage">Step 0</p>
<button onclick="window.count=(window.count||0)+1;document.querySelector('#stage').textContent='Step '+window.count">次へ</button>
<button onclick="window.wrong=(window.wrong||0)+1">戻る</button>
<button onclick="window.wrong=(window.wrong||0)+1">ヘルプ</button>'''

def flow_args(semantic=False):
    return {'expected_url':'about:blank','steps':[
        {'action':'click','target':'次の段階に進む。戻る・ヘルプではない。',
         'candidates':[{'role':'button','name':name} for name in (['次へ','戻る','ヘルプ'] if semantic else ['次へ'])],
         'expect':{'selector':'#stage','text':'Step '+str(i+1),'timeout_ms':1000}} for i in range(6)]}

def stats(rows):
    values=sorted(r['elapsed_ms'] for r in rows if r['verified'])
    return {'runs':len(rows),'verified':sum(r['verified'] for r in rows),
        'p50_ms':round(statistics.median(values),2) if values else None,
        'p95_ms':values[math.ceil(len(values)*.95)-1] if values else None,
        'handoffs':sum(bool(r.get('reason')) for r in rows)}

async def benchmark(args):
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    os.environ['DAN_BROWSER_TIMING_LOG']=str(output.with_suffix('.timing.jsonl'))
    groups={}
    api_calls=[0]
    original_choose=Decisions.choose
    async def bounded_choose(self, state, questions):
        from scripts.jev_trial_budget import reserve
        if not args.live or not reserve(state,questions):
            return {'available':False,'reason':'evaluation_call_cap'}
        api_calls[0] += 1
        return await original_choose(self,state,questions)
    with patch.dict(os.environ, {'DAN_COMMAND_JOB_ID':'', 'DAN_JEV_BROWSER_ENABLED':'1' if args.live else '0'}), patch('app.tools.browser._browser_room_id',lambda:''), patch.object(Decisions,'choose',bounded_choose):
        async with async_playwright() as pw:
            browser=await pw.chromium.launch()
            page=await browser.new_page()
            proxy=PageAdapter(page)
            try:
                with patch('app.tools.browser.get_executor_page',AsyncMock(return_value=proxy)):
                    modes=['individual','existing_fast','exact_plan']+(['jev_plan','jev_flow'] if args.live else [])
                    for workload in ('form','flow'):
                        for run in range(args.rounds+1):
                            order=modes[run%len(modes):]+modes[:run%len(modes)]
                            for mode in order:
                                if workload=='form' and mode=='jev_flow':continue
                                await page.set_content(FORM if workload=='form' else FLOW)
                                await page.evaluate('window.count=0;window.wrong=0;window.submissions=0')
                                elements=await proxy.get_interactive_elements()
                                started=time.perf_counter()
                                result={}
                                if mode in {'individual','existing_fast'}:
                                    if workload=='form':
                                        fields=[{'ref':next(e['ref'] for e in elements if e.get('id')=='f'+str(i)), 'value':'sample-'+str(i)} for i in range(8)]
                                        if mode=='existing_fast':
                                            result=await _execute_browser_tool('fill_form',{'fields':fields,'expected_url':page.url,'observation':'full'})
                                        else:
                                            for field in fields:
                                                result=await _execute_browser_tool('type',{'ref':field['ref'],'text':field['value'],'observation':'full'})
                                    else:
                                        ref=next(e['ref'] for e in elements if e.get('text')=='次へ')
                                        for i in range(6):
                                            call={'ref':ref,'observation':'full'}
                                            if mode=='existing_fast':call['expect']={'selector':'#stage','text':'Step '+str(i+1),'timeout_ms':1000}
                                            result=await _execute_browser_tool('click',call)
                                            assert await page.locator('#stage').inner_text()=='Step '+str(i+1)
                                elif mode=='jev_flow':
                                    from app.services.browser_flow import run as run_flow
                                    result=await run_flow({'expected_url':page.url,'goal':'次へボタンで段階を進めてStep 6にする。戻るやヘルプは使わない。',
                                        'candidates':[{'role':'button','name':name} for name in ['次へ','戻る','ヘルプ']],
                                        'until':{'selector':'#stage','text':'Step 6'},'max_steps':6},user_id=args.user_id)
                                else:
                                    params=form_args(mode=='jev_plan') if workload=='form' else flow_args(mode=='jev_plan')
                                    result=await plan.run(params,user_id=args.user_id)
                                elapsed=round((time.perf_counter()-started)*1000,2)
                                if workload=='form':
                                    verified=await page.locator('input').evaluate_all('els=>els.map(e=>e.value)')==['sample-'+str(i) for i in range(8)]
                                    verified=verified and await page.evaluate('window.submissions')==0
                                else:
                                    verified=await page.evaluate('window.count===6 && window.wrong===0')
                                verified=bool(verified and result.get('success'))
                                row={'elapsed_ms':elapsed,'verified':verified,'reason':result.get('reason'),'decision_calls':result.get('decision_calls',0)}
                                if run: groups.setdefault(workload+'/'+mode,[]).append(row)
                                print(json.dumps({'workload':workload,'mode':mode,'warmup':run==0,**row}),flush=True)
            finally:
                await page.screenshot(path=str(output.with_suffix('.png')))
                await browser.close()
    result={'scope':'Isolated Chromium; real production actions/observations; no Astra reasoning or production user sites.',
        'live_jev':args.live,'api_attempts':api_calls[0], 'rounds':args.rounds,
        'summary':{k:stats(rows) for k,rows in groups.items()},'samples':groups}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result['summary'],indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--user-id')
    parser.add_argument('--rounds',type=int,default=5)
    parser.add_argument('--output',default='scratch/jev-speed-audit-20260917/plan-benchmark.json')
    args=parser.parse_args()
    if args.live and not args.user_id:parser.error('--live requires --user-id')
    if not 1<=args.rounds<=20:parser.error('--rounds must be 1..20')
    asyncio.run(benchmark(args))
