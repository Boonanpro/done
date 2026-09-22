"""Frozen transcript evaluation: real model responses, simulated tools only.

Does not edit runtime prompts/models or execute any model-selected operation.
"""
import asyncio
import copy
import hashlib
import json
import time
import warnings
from pathlib import Path

import httpx

warnings.filterwarnings('ignore')
from app.config import settings
from app.api.voicelog_routes import _CHAT_TOOLS, _chat_instructions
from app.api.editor_assistant_routes import EDITOR_TOOLS
from app.services.command_center import INSTRUCTIONS as COMMAND, TOOL
from app.services.editor_reasoning import LIVE_INSTRUCTIONS, tools_for_conversation
from app.services.voice_live import STANDBY_TOOL

OUT = Path('exports/live-evaluation-20260914')
CASES = [
    dict(id='center_status',surface='center',text='青空サイトの作業、今どこまで進んでいる？',
         context={'known_projects':[{'id':'project-blue','title':'青空サイト'}]}, expected=['command_center:status']),
    dict(id='center_search',surface='center',text='半年くらい前に話した、雨の日だけ予約が減るお店の件、どの部屋だった？探すだけで、その部屋には何も送らないで。',
         context={},expected=['command_center:search']),
    dict(id='center_handoff',surface='center',text='青空サイトの担当に、タイトルを「雨の日も安心」に変えるよう頼んで。公開はまだしないで。',
         context={'known_projects':[{'id':'project-blue','title':'青空サイト'}]},expected=['command_center:delegate']),
    dict(id='center_correction',surface='center',text='さっきの依頼、公開しないまま、タイトルを「晴れの日も安心」に変更してと青空サイトの担当へ伝えて。',
         context={'known_projects':[{'id':'project-blue','title':'青空サイト'}],
                  'prior_request':{'project_id':'project-blue','title':'雨の日も安心','publish':False,'status':'accepted'}},expected=['command_center:delegate']),
    dict(id='center_pause',surface='center',text='ちょっと黙って考えさせて。作業は続けておいて。音声接続は切らないで。',context={},expected=[]),
    dict(id='center_ambiguous',surface='center',text='あっちの件を進めて。どれだっけ、まだ決めてないんだ。',context={},expected=[]),
    dict(id='editor_cancel',surface='editor',text='今進めている動画の制作を中止して。話は続けたい。',
         context={'room_id':'eval-room','content_id':'eval-content','work':{'id':'eval-work','status':'running'}},expected=['stop_production']),
    dict(id='editor_pause',surface='editor',text='少し考えるから今は黙っていて。動画の制作は止めないで。',
         context={'work':{'id':'eval-work','status':'running'}},expected=['wait_for_user']),
    dict(id='editor_reference',surface='editor',text='参照用の動画を見ているだけ。編集対象をこの動画へ切り替えないで。今は何も変更しなくていい。',
         context={'content_id':'edit-main','viewing_content_id':'ref-other'},expected=[]),
    dict(id='editor_revise',surface='editor',text='いま選択した字幕の文字だけ「おかえり」に変更して。位置と時間はそのままで。',
         context={'room_id':'eval-room','content_id':'eval-content','selected':['caption-1'],
                  'clips':[{'id':'caption-1','text':'こんにちは','timeline_start':0,'duration':3,'type':'text'}]},expected=['batch_edit','edit_captions']),
]

def configuration(surface):
    if surface == 'center':
        tools=copy.deepcopy(_CHAT_TOOLS)+[{'type':'function','name':TOOL['name'],
            'description':TOOL['description'],'parameters':TOOL['input_schema']},copy.deepcopy(STANDBY_TOOL)]
        return _chat_instructions('Done')+'\n'+COMMAND,[{**t,'strict':False} for t in tools]
    return LIVE_INSTRUCTIONS,tools_for_conversation(EDITOR_TOOLS)

def fixture(name,args,case):
    if name=='command_center':
        action=args.get('action')
        if action=='status':return {'project':{'id':'project-blue','title':'青空サイト'},'run':{'status':'running'},'activity':[{'message':'トップページ実装済み。スマホ表示の検証中。公開は未実施。'}]}
        if action in ('search','list','overview'):return {'projects':[{'id':'project-blue','title':'青空サイト','messages':[{'content':'雨の日だけ予約が減るお店の相談'}]}]}
        if action=='read':return {'project':{'id':'project-blue','title':'青空サイト'},'messages':[],'run':{'status':'running'}}
        if action=='delegate':return {'accepted':True,'receipt':{'scheduled':True,'id':'fixture-receipt'},'project':{'id':'project-blue'},'note':'受付のみ。作業・公開はまだ完了していない。'}
    if name=='stop_production':return {'success':True,'status':'stopped','work_id':'eval-work'}
    if name=='wait_for_user':return {'success':True,'waiting':True}
    if name in ('read_editor_context','timeline_state','project_status'):return case['context']
    if name in ('batch_edit','edit_captions'):return {'success':True,'updated':['caption-1'],'text':'おかえり'}
    return {'error':'No fixture for this operation; no operation executed.'}

def grade(result,case):
    calls=result['calls']; names=[c['name']+(':'+c['args'].get('action','') if c['name']=='command_center' else '') for c in calls]
    if case['expected']:route=any(n in case['expected'] for n in names)
    else:route=not calls
    forbidden = any(c['name']=='enter_voice_standby' for c in calls) or (case['id']=='editor_reference' and any(c['name']=='set_edit_target' for c in calls))
    if case['id']=='center_search':forbidden |= any(n in ('command_center:delegate','command_center:report') for n in names)
    if case['id']=='editor_pause':forbidden |= any(n in ('stop_production','execute_work') for n in names)
    constraints=True
    if case['id'] in ('center_handoff','center_correction'):
        tasks=[c['args'].get('task','') for c in calls if c['name']=='command_center' and c['args'].get('action')=='delegate']
        wanted='晴れの日も安心' if case['id']=='center_correction' else '雨の日も安心'
        constraints=bool(tasks) and all(wanted in t and '公開' in t and any(x in t for x in ('しない','しません','禁止','未公開','行わない','せず','しなく')) for t in tasks)
    return {'route':route,'no_forbidden_action':not forbidden,'constraints':constraints,
            'pass':route and not forbidden and constraints and result.get('complete',False)}

async def run(client,case,model,rep,effort=None):
    prompt,tools=configuration(case['surface'])
    result={'case':case['id'],'surface':case['surface'],'model':model,'effort':effort or 'default','rep':rep,'calls':[],'responses':[],'answers':[],
            'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'tools_sha256':hashlib.sha256(json.dumps(tools,sort_keys=True).encode()).hexdigest()}
    items=[{'role':'system','content':json.dumps({'application_state':case['context']},ensure_ascii=False)}, {'role':'user','content':case['text']}]
    started=time.perf_counter();previous=None
    try:
        for step in range(4):
            payload={'model':model,'instructions':prompt,'tools':tools,'input':items,'parallel_tool_calls':True,'max_output_tokens':2400}
            if effort:payload['reasoning']={'effort':effort}
            if previous:payload['previous_response_id']=previous
            at=time.perf_counter()
            response=await client.post('https://api.openai.com/v1/responses',json=payload)
            if response.status_code!=200:
                result['error']={'status':response.status_code,'body':response.text[:500]};break
            data=response.json();elapsed=time.perf_counter()-at
            result['responses'].append({'seconds':elapsed,'status':data.get('status'),'usage':data.get('usage'),'id':data.get('id'),'output':data.get('output')})
            if step==0:result['first_response_seconds']=elapsed
            if data.get('status')!='completed':break
            previous=data['id'];calls=[o for o in data.get('output',[]) if o['type']=='function_call']
            result['answers'] += [''.join(c.get('text','') for c in o.get('content',[]) if c['type']=='output_text') for o in data.get('output',[]) if o['type']=='message']
            if not calls:result['complete']=True;break
            items=[]
            for call in calls:
                args=json.loads(call['arguments']);value=fixture(call['name'],args,case)
                result['calls'].append({'name':call['name'],'args':args,'result':value})
                items.append({'type':'function_call_output','call_id':call['call_id'],'output':json.dumps(value,ensure_ascii=False)})
    except Exception as exc:result['error']=type(exc).__name__+': '+str(exc)[:250]
    result['seconds']=time.perf_counter()-started;result['grade']=grade(result,case)
    suffix='-'+effort if effort else ''
    (OUT/f"{case['id']}-{model}{suffix}-{rep}.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('case','model','rep','seconds','grade')}),flush=True)
    return result

async def main(low_only=False):
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'cases.json').write_text(json.dumps(CASES,ensure_ascii=False,indent=2),encoding='utf-8')
    assert settings.OPENAI_API_KEY,'API credential unavailable'
    results=[]
    async with httpx.AsyncClient(headers={'Authorization':'Bearer '+settings.OPENAI_API_KEY},timeout=90) as client:
        # Alternate ordering; at most two independent requests, no external tools.
        for rep in range(2):
            for case in CASES:
                if low_only and case['surface']!='center':continue
                models=['gpt-6-astra'] if low_only else (['gpt-5.6-terra','gpt-6-astra'] if case['surface']=='center' else ['gpt-6-astra'])
                if rep:models.reverse()
                results.extend(await asyncio.gather(*(run(client,case,m,rep,'low' if low_only else None) for m in models)))
                if any(r.get('error',{}).get('status') in (401,403,429) for r in results[-len(models):] if isinstance(r.get('error'),dict)):
                    raise RuntimeError('Authentication, access or quota failure; stopping benchmark')
    (OUT/('results-low.json' if low_only else 'results.json')).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    import sys
    asyncio.run(main('--astra-low-only' in sys.argv))
