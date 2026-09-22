"""Follow-up evaluation with the real search's literal-substring semantics."""
import asyncio
import json
from pathlib import Path

import httpx
from scripts import evaluate_live_backends as bench

ORIGINAL = bench.fixture
MESSAGE = '雨の日だけ予約が減るお店の相談'

def fixture(name,args,case):
    if name=='command_center':
        action=args.get('action')
        if action=='search':
            terms=args.get('keywords') or str(args.get('query') or '').split()
            hits=[t for t in terms if t.casefold() in MESSAGE.casefold()]
            projects=[{'id':'project-blue','title':'青空サイト','matched_terms':hits,
                       'messages':[{'sender_type':'human','content':MESSAGE}]}] if hits else []
            return {'projects':projects,'terms':terms,'matching_projects':len(projects),'next_offset':None}
        if action=='overview':return {'projects':[],'total':0,'note':'直近30日以内の会話はありません。'}
        if action=='read':return {'project':{'id':'project-blue','title':'青空サイト'},'messages':[{'sender_type':'human','content':MESSAGE}]}
    return ORIGINAL(name,args,case)

async def main():
    bench.OUT=Path('exports/live-evaluation-20260914/search-semantics');bench.OUT.mkdir(exist_ok=True)
    bench.fixture=fixture
    case=next(c for c in bench.CASES if c['id']=='center_search')
    rows=[]
    async with httpx.AsyncClient(headers={'Authorization':'Bearer '+bench.settings.OPENAI_API_KEY},timeout=90) as client:
        for rep in range(2):
            arms=[('gpt-5.6-terra',None),('gpt-6-astra',None),('gpt-6-astra','low')]
            if rep:arms.reverse()
            for model,effort in arms:rows.append(await bench.run(client,case,model,rep,effort))
    (bench.OUT/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':asyncio.run(main())
