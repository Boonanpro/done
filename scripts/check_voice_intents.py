"""Compare old/new Jev wording on fixed Japanese cases; only API decisions, no actions."""
import asyncio
import ast
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


async def main():
    from dotenv import load_dotenv
    load_dotenv(Path.home()/'done/.env')
    from app.services import voice_prefetch as P, jev_browser_budget as budget
    from app.services.jev_decisions import Decisions
    from scripts.check_voice_laya import CASES
    old=ast.parse(subprocess.check_output(['git','show','9512ea13:app/services/voice_prefetch.py'],text=True,cwd=ROOT))
    old_kinds=next(ast.literal_eval(n.value) for n in old.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='KINDS' for t in n.targets))
    user='2582a188-ff24-4a4f-b989-6063034d90b2'
    budget.PATH=ROOT/'.tmp/voice-early/jev-intents-budget.json'
    if not budget.PATH.exists(): budget.PATH.write_text(json.dumps(dict(enabled=True,publish=True,user_id=user,approved_usd=.1,reserved_usd=0,requests=0,max_requests=90)))
    output={}
    async with Decisions(user,timeout=3,max_calls=90) as judge:
        for name,kinds in [('baseline',old_kinds),('after',P.KINDS)]:
            rows=[]
            for text,expected in CASES:
                r=await judge.choose({'utterance_so_far':text},{'kind':{'type':'choice','criteria':kinds,'instructions':P.ASK}})
                a=r.get('answers',{}).get('kind',{})
                rows.append(dict(text=text,expected=expected,choice=a.get('choice'),correct=a.get('choice')==expected,ms=r['elapsed_ms']))
                if not r.get('available'): break
            output[name]=rows
    (ROOT/'.tmp/voice-early/jev-intents.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
    for name,rows in output.items(): print(name,sum(x['correct'] for x in rows),len(rows))


if __name__=='__main__':asyncio.run(main())
