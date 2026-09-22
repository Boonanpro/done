"""Controlled scheduling benchmark; no external services or model calls."""
import asyncio
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.agent.cli_runner import _prepare_cli_inputs

async def measure(mode):
    ticks=[]
    started=time.perf_counter()
    async def pulse():
        for _ in range(30):
            await asyncio.sleep(.01)
            ticks.append(time.perf_counter()-started)
    def prompt(**kwargs):
        time.sleep(.2)
        return 'identical current rules'
    def config(*args):
        time.sleep(.1)
        return 'isolated config'
    async def build():
        await asyncio.sleep(0)
        if mode=='sequential_blocking':
            result=[prompt(),config()]
        else:
            result=await _prepare_cli_inputs('r','u',None,None,None,{})
        return result,(time.perf_counter()-started)*1000
    with patch('app.agent.cli_runner._build_system_prompt',prompt),patch('app.agent.cli_runner._build_mcp_config',config):
        (result,elapsed),_=await asyncio.gather(build(),pulse())
    assert result==['identical current rules','isolated config']
    gaps=[ticks[0]]+[b-a for a,b in zip(ticks,ticks[1:])]
    return {'preparation_ms':round(elapsed,2),'max_heartbeat_gap_ms':round(max(gaps)*1000,2),'identical_inputs':True}

async def main():
    data={'scope':'Controlled 200ms prompt read + 100ms config write; demonstrates event-loop scheduling, not measured production latency.'}
    for mode in ('sequential_blocking','concurrent_threads'):
        data[mode]=[await measure(mode) for _ in range(5)]
    p=ROOT/'scratch/jev-speed-audit-20260917/preparation-benchmark.json'
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,indent=2),encoding='utf-8')
    print(json.dumps(data,indent=2))

if __name__=='__main__':asyncio.run(main())
