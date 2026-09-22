"""Measure destination evidence versus the existing redirect grace, isolated."""
import asyncio
import json
import os
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import AsyncMock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from playwright.async_api import async_playwright
from scripts.benchmark_browser_plan import PageAdapter
from app.agent.v2.tools import _execute_browser_tool

async def main():
    out=ROOT/'scratch/jev-speed-audit-20260917'
    fixture=out/'ready-fixture.html'
    fixture.write_text('<h1 id="destination" hidden>Fixture destination</h1><script>setTimeout(()=>document.querySelector("h1").hidden=false,150)</script>',encoding='utf-8')
    os.environ['DAN_BROWSER_TIMING_LOG']=str(out/'ready-timing.jsonl')
    samples={'legacy':[],'evidence':[]}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        page=await browser.new_page();proxy=PageAdapter(page)
        try:
            with patch('app.tools.browser.get_executor_page',AsyncMock(return_value=proxy)),patch('app.tools.browser._browser_room_id',lambda:''):
                for trial in range(3):
                    for mode in (['legacy','evidence'] if trial%2==0 else ['evidence','legacy']):
                        args={'url':fixture.as_uri(),'observation':'full'}
                        if mode=='evidence':args['ready']={'selector':'#destination','text':'Fixture destination','timeout_ms':1000}
                        start=time.perf_counter();result=await _execute_browser_tool('open_target',args)
                        elapsed=round((time.perf_counter()-start)*1000,2)
                        assert result['success'] and await page.locator('#destination').is_visible()
                        if mode=='evidence':assert result['authentication']=='unverified'
                        samples[mode].append(elapsed)
                        print(json.dumps({'mode':mode,'elapsed_ms':elapsed,'verified':True}),flush=True)
        finally:await browser.close()
    result={'scope':'Isolated local destination appears after 150ms; full final observations; no authentication assertion or model.',
        'samples_ms':samples,'medians_ms':{k:statistics.median(v) for k,v in samples.items()}}
    (out/'ready-benchmark.json').write_text(json.dumps(result,indent=2),encoding='utf-8')

asyncio.run(main())
