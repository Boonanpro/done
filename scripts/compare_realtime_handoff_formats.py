"""Isolated real-model comparison. All app tools are simulated; no production job runs."""
import asyncio,copy,hashlib,json,re,time
from pathlib import Path
import websockets
from app.config import settings
from app.api.editor_assistant_routes import EDITOR_TOOLS,EDITOR_INSTRUCTIONS,REALTIME_MODEL

OUT=Path('exports/realtime-handoff-comparison-20260909')
OUT.mkdir(parents=True,exist_ok=True)
original=json.loads(Path('uploads/production-assets/2c1c50e1-61c4-44eb-99e5-8f78905ab200/assistant/69d83927255e4990b598ecfb773c007f.json').read_text(encoding='utf-8'))['context']['utterance']
CASES=[
 {'id':'soccer','messages':[('user',original)],
  'reference':'参考ref1は、写真・目・手・封筒・テープなどの前景レイヤーが次々に重なり、急な寄りや変形でつながるコラージュ映像。モノクロに黄と赤の差し色。ユーザーは動画全体の感じを参考にしたいと述べた。',
  'brief':{},'facts':['日本','ブラジル','フランス','オランダ','優勝']},
 {'id':'tentative','messages':[
  ('user','仕事帰りの人に、一人でも入りやすそうと思ってもらえる焼き鳥屋の動画を作りたい。参考の雰囲気は好き。'),
  ('assistant','人物を映さず、料理と文字だけで見せる案も考えられます。'),
  ('user','人物を映さないとは決めてないよ。そこはそっちで考えて。参考みたいな感じでまず見せて。')],
  'reference':'参考ref1は、人の表情、料理の接写、短い文字がテンポよく切り替わる店の紹介動画。',
  'brief':{},'facts':['焼き鳥','一人']},
 {'id':'budget_change','messages':[
  ('user','まずは無料の範囲で見本を考えて。'),
  ('assistant','無料素材とコードで試す方針にします。'),
  ('user','今の見本じゃ判断できない。無料だけという条件は取り消す。GoogleのOmniを直接使って、5秒一本、1ドルまでなら使って良い。Higgsfieldのクレジットは使わないで。')],
  'reference':'参考ref1は、紙のレイヤーと動く人物を使ったサッカーのコラージュ。',
  'brief':{'intent':'日本がブラジルに勝つ架空のコラージュ動画','constraints':'無料素材とコードだけで試作する。'},
  'facts':['Google','5秒','1ドル','Higgsfield']},
]

def variant(arm):
    tools=copy.deepcopy(EDITOR_TOOLS);instructions=EDITOR_INSTRUCTIONS
    if arm!='A_current':
        tools=[t for t in tools if t['name']!='save_brief']
        instructions='\n'.join(line for line in instructions.splitlines() if 'save_brief' not in line)
        instructions+='\n会話はアプリがそのまま記録します。制作方針を欄に整理して保存する作業はありません。'
    if arm=='C_raw':
        tools=[t for t in tools if t['name']!='delegate_edit']
        tools.append({'type':'function','name':'request_production','description':'GPT6に制作・調査を依頼する。アプリがこの会話の原文、参考情報、現在の作品状態をそのまま渡す。引数不要。',
                      'parameters':{'type':'object','properties':{},'required':[]}})
        instructions=instructions.replace('delegate_edit(task_kind=prepare)','request_production').replace('delegate_edit(task_kind=edit)','request_production').replace('delegate_edit','request_production')
        instructions+='\nrequest_productionでは依頼文を書き直さず呼び出します。元の発言と役割付き会話がアプリから制作側に渡ります。'
    return instructions,tools

async def run(arm,case,repeat):
    path=OUT/f"{case['id']}-{arm}-{repeat}.json"
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    instructions,tools=variant(arm)
    context={'content_id':'isolated-comparison','duration':0,'clips':[],
             'creative_brief':case['brief'],'reference_ids':['ref1'],'reference_description':case['reference']}
    record={'arm':arm,'case':case['id'],'repeat':repeat,'model':REALTIME_MODEL,
            'input_messages':case['messages'],'context':context,'instructions':instructions,'tools':tools,
            'events':[],'calls':[],'responses':[],'handoff':None,'completed':False}
    started=time.monotonic()
    try:
        async with websockets.connect('wss://api.openai.com/v1/realtime?model='+REALTIME_MODEL,
              additional_headers={'Authorization':'Bearer '+settings.OPENAI_API_KEY},max_size=8*1024*1024,open_timeout=30) as ws:
            async def send(data):await ws.send(json.dumps(data,ensure_ascii=False))
            await send({'type':'session.update','session':{'type':'realtime','model':REALTIME_MODEL,
                'instructions':instructions,'tools':tools,'reasoning':{'effort':'high'},
                'max_output_tokens':4096,'output_modalities':['text'],
                'truncation':{'type':'retention_ratio','retention_ratio':.7,'token_limits':{'post_instructions':6000}}}})
            while True:
                e=json.loads(await asyncio.wait_for(ws.recv(),30))
                if e['type']=='error':raise RuntimeError(str(e['error']))
                if e['type']=='session.updated':break
            await send({'type':'conversation.item.create','item':{'type':'message','role':'system','content':[{'type':'input_text','text':'現在の作品状態:\n'+json.dumps(context,ensure_ascii=False)}]}})
            for role,text in case['messages']:
                await send({'type':'conversation.item.create','item':{'type':'message','role':role,'content':[{'type':'output_text' if role=='assistant' else 'input_text','text':text}]}})
            for _ in range(6):
                await send({'type':'response.create','response':{'output_modalities':['text']}})
                while True:
                    e=json.loads(await asyncio.wait_for(ws.recv(),75))
                    if e['type']=='error':raise RuntimeError(str(e['error']))
                    if e['type']=='response.done':break
                response=e['response'];record['responses'].append(response)
                if response.get('status')!='completed':raise RuntimeError(str(response.get('status_details')))
                calls=[o for o in response.get('output',[]) if o.get('type')=='function_call']
                for call in calls:
                    name=call['name'];args=json.loads(call['arguments'])
                    record['calls'].append({'name':name,'args':args,'at_seconds':round(time.monotonic()-started,3)})
                    if name in {'delegate_edit','request_production'}:
                        record['handoff']={'instruction':args.get('instruction'),'raw_messages':case['messages'],
                                           'reference_description':case['reference'],'task_kind':args.get('task_kind')}
                    if name in {'read_editor_context','timeline_state'}:result={'ok':True,**context}
                    elif name in {'read_references','resolve_reference'}:
                        result={'ok':True,'references':[{'id':'ref1','analysis':case['reference']}],'item':{'kind':'video','reference_id':'ref1','title':'参考'}}
                    elif name=='save_brief':result={'ok':True,'saved':args}
                    elif name=='project_status':result={'ok':True,'active_count':0,'active_jobs':[]}
                    elif name in {'delegate_edit','request_production'}:result={'ok':True,'job_id':'simulated-no-execution'}
                    elif name=='list_assets':result={'ok':True,'assets':[]}
                    else:result={'ok':True}
                    await send({'type':'conversation.item.create','item':{'type':'function_call_output','call_id':call['call_id'],'output':json.dumps(result,ensure_ascii=False)}})
                if record['handoff'] or not calls:break
            record['completed']=True
    except Exception as exc:record['error']=str(exc)[:1200]
    record['elapsed_seconds']=round(time.monotonic()-started,3)
    path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(case['id'],arm,repeat,'handoff',bool(record['handoff']),'calls',[c['name'] for c in record['calls']],'seconds',record['elapsed_seconds'],record.get('error',''),flush=True)
    return record

async def main():
    sem=asyncio.Semaphore(2)
    async def one(*args):
        async with sem:return await run(*args)
    # Two repeats, rotating arm order; no optional stopping based on outcomes.
    tasks=[]
    for rep in range(2):
        for case in CASES:
            arms=['A_current','B_no_form','C_raw']
            if rep:arms=arms[1:]+arms[:1]
            for arm in arms:tasks.append(one(arm,case,rep))
    results=await asyncio.gather(*tasks)
    (OUT/'manifest.json').write_text(json.dumps({'protocol':'3 arms x 3 cases x 2 repeats; text transcript input to Realtime high; tools simulated; production never runs',
        'results':[{'case':r['case'],'arm':r['arm'],'repeat':r['repeat'],'completed':r['completed'],'handoff':bool(r['handoff']),'error':r.get('error')} for r in results]},ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':asyncio.run(main())
