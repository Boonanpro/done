"""Real Jev/CLI + real editor player, isolated text-conversation replay.

No microphone, TTS, user timeline or production restart. This measures from
submission of an already-transcribed utterance through image decode and paint.
"""
import asyncio,json,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'scratch/reference-library-display-20260917'

async def main():
 import httpx
 from playwright.async_api import async_playwright
 from app.services.editor_codex import stream_response
 from app.services import timeline_draft as td
 OUT.mkdir(exist_ok=True)
 room='library-test-'+uuid.uuid4().hex[:8];cid='reference-test'
 folder=td._room_dir(room);folder.mkdir(parents=True,exist_ok=True)
 seq={'format':'16:9','duration':3,'tracks':[{'id':'v','type':'video','clips':[]}]}
 (folder/'contents.json').write_text(json.dumps([{'id':cid,'timeline':{'format':'16:9','sequence':seq}}]),encoding='utf-8')
 (folder/'assets.json').write_text('[]',encoding='utf-8')
 token=(Path.home()/'.done/native_token.txt').read_text().strip()
 base='http://127.0.0.1:8012/api/v1/editor-assistant'
 dialogue=[];items=[];results=[]
 utterances=[
  'シリアスな体験談の動画を考えています。テレビの再現イラストみたいな感じだけど、うまく言えません。まず雰囲気の違う参考を2つ見せてください。',
  '写実的なほうより、手描きの漫画っぽい感じが近いです。でも笑っている絵では想像しづらいので、不安や困っている場面を見せてください。',
  '人物が違うだけではなく、この漫画風の方向で、描き方が少し違う参考を見たいです。',
  'やっぱり実写で、人物がスマホを置いて取り直す動画を見たいです。画像では判断できません。ネットを検索したり新しく生成したりはしないでください。',
 ]
 async with httpx.AsyncClient(timeout=120,headers={'Authorization':'Bearer '+token}) as client, async_playwright() as p:
  b=await p.chromium.launch(headless=True);page=await b.new_page(viewport={'width':1280,'height':900})
  await page.goto(base+'/page')
  await page.wait_for_function('typeof window.__updateEditorContext === "function"')
  await page.evaluate('({token,room,cid})=>{window.__editorBootstrap={token};window.__updateEditorContext({room_id:room,content_id:cid,playhead:0,selected:[]});}',{'token':token,'room':room,'cid':cid})
  for n,utterance in enumerate(utterances):
   dialogue.append({'role':'user','text':utterance});started=time.perf_counter()
   r=await client.post(base+'/reference-library/decision',json={'dialogue':dialogue,'items':items});r.raise_for_status();decision=r.json();decision_ms=round((time.perf_counter()-started)*1000)
   begin=await client.post(base+'/begin',json={'room_id':room,'content_id':cid,'live_dialogue':dialogue,'reference_library':decision,'utterance':utterance})
   begin.raise_for_status();turn=begin.json();tool_calls=[];selected=[]
   if decision.get('handled'):
    selected=decision['selected_library_ids'];route=decision.get('selection_backend','jev')
   else:
    route='astra';response=None
    tools=[{'type':'function','name':'present_reference_examples','description':'Show 1-3 appropriate inspected references. Do not force a match.','parameters':{'type':'object','properties':{'ids':{'type':'array','items':{'type':'string'}}},'required':['ids']}}]
    prompt='You are Dan. Keep prior accepted/rejected preferences. Use only supplied inspected candidates. Show suitable references with the tool. If none fit, briefly say the library lacks them, do not search or generate. Different person is not different drawing style. No other tools.'
    async for e in stream_response([{'role':'user','content':json.dumps({'dialogue':dialogue,'library':decision,'displayed':items},ensure_ascii=False)}],tools,prompt,'gpt-6-astra'):
     if e['type']=='completed':response=e
    calls=[e for e in response['output'] if e.get('type')=='function_call']
    if calls:
     selected=json.loads(calls[0]['arguments'])['ids'];tool_calls=calls
    # A one-shot evaluation does not leave a suspended CLI process alive.
    from app.services import editor_codex
    for call in calls:
     pending=editor_codex._pending.pop(call['call_id'],None)
     if pending:pending[0].close()
   if selected:
    r=await client.post(base+'/tool',json={'room_id':room,'turn_id':turn['turn_id'],'name':'present_reference_examples','args':{'ids':selected}});r.raise_for_status();shown=r.json();items=shown['presentation']['items']
    paint_start=time.perf_counter()
    display=await page.evaluate('''async p=>{renderReferences(p);return await presentationReady(p);}''',shown['presentation'])
    assert display['ok']
    paint_ms=round((time.perf_counter()-paint_start)*1000)
    dialogue.append({'role':'assistant','text':'提示した参考: '+json.dumps([{'title':i['title'],'source_url':i.get('source_url')} for i in items],ensure_ascii=False)})
   else:dialogue.append({'role':'assistant','text':'知識庫には条件に合う実物がありません。'});paint_ms=None
   result={'turn':n+1,'utterance':utterance,'route':route,'selected':selected,'submission_to_paint_ms':round(1000*(time.perf_counter()-started)),'decision_ms':decision_ms,'paint_ms':paint_ms,'ranking_ms':decision.get('ranking_ms'),'scores':{k:v.get('score',v.get('noul')) for k,v in decision.get('scores',{}).items()}}
   await page.screenshot(path=str(OUT/f'turn-{n+1}.png'))
   results.append(result);(OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False),flush=True)
  await page.screenshot(path=str(OUT/'conversation.png'),full_page=True)
  assert td._find_content(td._read_contents_raw(room),cid)['timeline']['sequence']==seq
  await b.close()
 (OUT/'scope.json').write_text(json.dumps({'room':room,'audio_test':False,'timeline_unchanged':True}),encoding='utf-8')

if __name__=='__main__':asyncio.run(main())
