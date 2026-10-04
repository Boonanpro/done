"""Real Astra decisions, real saved visuals; production handoffs are captured, not executed.

No target artifact is supplied to the model. Each fixture describes the user's
creative uncertainty, then accepts Dan's own proposal without naming a tool.
"""
import asyncio
import json
import time
import uuid
from pathlib import Path

from openai import AsyncOpenAI
from app.config import settings
from app.services.editor_consultation_sheet import empty, update, tools, BACKEND_INSTRUCTIONS
from app.services import editor_presentation, timeline_draft as td

OUT = Path('scratch/first-artifact-milestone')
CASES = [
    ('appearance', '映画の予告', '自宅の作業場で翼付き自動車を開発する男', '30秒',
     '写実的で現実味のある映画。人の顔や作業場の質感はまだ具体的に想像できない。',
     'うん、方向はその感じがいい。まだ頭の中で見た目がぼんやりしてるけど。'),
    ('motion', '文字と図形の製品ローンチ動画', '散らばった情報が一つにまとまるメモアプリ', '15秒',
     '紺と白のミニマルな図形と文字。素材画像や人物は不要。静止画の見た目は決まったが、情報がまとまる気持ちよさや間はまだ不明。',
     'うん、その方向で。色とかは今ので良いけど、動いた時に気持ち良いかはまだ分からんな。'),
    ('spatial', '倉庫作業の研修動画', '棚の死角から来る台車を人が避ける', '20秒',
     '白黒の簡単な立体で十分。人と台車のすれ違い、棚との位置関係を斜め上から見たい。完成の肌や質感は今は不要。',
     'うん。人と台車がどこですれ違うか、カメラからちゃんと見えるかが気になってる。'),
    ('narrative', '歴史の解説動画', '電気が家庭に普及するまでの変化', '3分',
     '古写真と図解。写真と図の見た目は決定済み。最初に生活の変化、次に仕組み、最後に今との比較。声と展開の間が退屈にならないか不明。',
     'うん。その見た目で良い。全体として話が面白く聞けるかが気になるね。'),
]

async def case(client, page, spec):
    name,kind,subject,duration,reference,utterance=spec
    room='first-artifact-'+name+'-'+uuid.uuid4().hex[:8]
    folder=td._room_dir(room);folder.mkdir(parents=True,exist_ok=True)
    cid='first-artifact-check'
    if not td._find_content(td._read_contents_raw(room),cid):
        td._write_contents_raw(room,[{'id':cid,'title':subject,'timeline':{'format':'16:9','sequence':{'format':'16:9','duration':0,'frame_rate':30,'tracks':[]}}}])
    sheet=update(empty(),[{'field':k,'status':'confirmed','value':v} for k,v in dict(
        video_type=kind,subject=subject,platform='YouTube',purpose='見る人に内容が伝わり興味を持ってもらう',
        audience='一般の大人',duration=duration,materials='手持ち素材なし',references=reference).items()],True)
    state={'sheet':sheet,'displayed':[],'production':{'running':False}}
    await page.evaluate('c=>{context=c}',{'room_id':room,'content_id':cid})
    inputs=[{'role':'user','content':utterance}]
    history=[]
    for turn in range(2):
        if turn:inputs.append({'role':'user','content':'うん。それで進めて。今回提案してくれた見本に必要な生成費用も使っていいよ。'})
        started=time.perf_counter();calls=[];text=''
        for _ in range(5):
            response=await client.responses.create(model='gpt-6-astra',instructions=BACKEND_INSTRUCTIONS,
                input=inputs,tools=tools(),reasoning={'effort':'low'},max_output_tokens=6500,store=False)
            inputs.extend(x.model_dump(exclude_none=True) for x in response.output)
            text+=response.output_text
            functions=[x for x in response.output if x.type=='function_call']
            if not functions:break
            for call in functions:
                args=json.loads(call.arguments);calls.append({'name':call.name,'args':args})
                if call.name=='get_consultation_state': result=state
                elif call.name=='update_consultation_sheet':
                    state['sheet']=update(state['sheet'],**args);result={'saved':True,'sheet':state['sheet']}
                elif call.name=='show_consultation_visual':
                    result=await page.evaluate('''async v=>executeLiveConsultationTool(
                      {name:'show_consultation_visual',call_id:v.id,arguments:JSON.stringify(v.args)},
                      {id:v.id,editContext:context},context)''',{'args':args,'id':call.call_id})
                    state['displayed']=result.get('items',[])
                    await page.screenshot(path=str(OUT/(name+f'-{turn}.png')))
                elif call.name=='control_reference':
                    result=await page.evaluate('''async v=>executeLiveConsultationTool(
                      {name:'control_reference',call_id:v.id,arguments:JSON.stringify(v.args)},
                      {id:v.id,editContext:context},context)''',{'args':args,'id':call.call_id})
                elif call.name=='run_editor_task':
                    result={'accepted':True,'completed':False,'note':'Evaluation captures this handoff. No production worker started.'}
                else:result={'ok':False,'reason':'This evaluation does not fetch new references or web results.'}
                calls[-1]['result']=result
                if call.name=='show_consultation_visual':assert result.get('shown'),result
                inputs.append({'type':'function_call_output','call_id':call.call_id,'output':json.dumps(result,ensure_ascii=False)})
            if any(x.name=='run_editor_task' for x in functions):break
        row={'turn':turn,'seconds':round(time.perf_counter()-started,2),'text':text,'calls':calls}
        history.append(row)
        (OUT/(name+'.json')).write_text(json.dumps({'case':name,'room':room,'content_id':cid,'turns':history},ensure_ascii=False,indent=2),encoding='utf8')
        print(name,turn,row['seconds'],[(c['name'],c['args'].get('artifact')) for c in calls],flush=True)
    calls=[c for t in history for c in t['calls']]
    if name in ('appearance','narrative'):
        artifact='look_frame' if name=='appearance' else 'vconte'
        assert any(c['name']=='run_editor_task' and c['args'].get('artifact')==artifact for c in calls),history
        assert not any(c['name']=='run_editor_task' for c in history[0]['calls']),history
    else:
        assert any(c['name']=='show_consultation_visual' for c in calls),history
        assert not any(c['name']=='run_editor_task' and c['args'].get('artifact') in ('look_frame','vconte') for c in calls),history
    return history

async def main():
    import sys
    from playwright.async_api import async_playwright
    OUT.mkdir(parents=True,exist_ok=True)
    async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY) as client, async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        try:
            for spec in CASES:
                if len(sys.argv)>1 and spec[0] not in sys.argv[1:]:continue
                page=await browser.new_page(viewport={'width':1440,'height':1000})
                await page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
                await page.evaluate('v=>window.__setEditorAuth(v)',{'token':(Path.home()/'.done/native_token.txt').read_text().strip()})
                await case(client,page,spec)
                await page.close()
        finally:await browser.close()

if __name__=='__main__':asyncio.run(main())
