"""Real Astra + browser tools. Scripted text turns, not an acoustic voice test."""
import asyncio
import json
import time
import sys
from pathlib import Path
from openai import AsyncOpenAI
from playwright.async_api import async_playwright
from app.config import settings
from app.services.editor_consultation_sheet import update, tools, BACKEND_INSTRUCTIONS

async def main():
    out=Path('scratch/film-plan-dialogue');out.mkdir(parents=True,exist_ok=True)
    sheet=update(None,[{'field':k,'status':'confirmed','value':v} for k,v in {
        'video_type':'短編映画','subject':'自宅の作業場で航空機を作る主人公',
        'purpose':'開発に挑む姿を面白く見せる','audience':'技術と映画が好きな人',
        'platform':'YouTube','duration':'30秒','materials':'なし',
        'references':'現実味のある実写調。参考の方向は合意済み'}.items()],True)
    async with async_playwright() as p, AsyncOpenAI(api_key=settings.OPENAI_API_KEY) as client:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        page=await browser.new_page(viewport={'width':1400,'height':1000})
        try:
            await page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
            from app.services.auth_service import create_access_token
            await page.evaluate('v=>window.__setEditorAuth(v)',{'token':create_access_token('film-plan-test','film-plan-test@localhost')})
            from app.services import timeline_draft as td
            previous=json.loads((out/'result.json').read_text(encoding='utf-8')) if '--resume' in sys.argv else None
            room=previous['owner']['room_id'] if previous else 'film-plan-check-'+str(time.time_ns())
            if not previous:
                td._room_dir(room).mkdir(parents=True)
                td._write_contents_raw(room,[{'id':'film','title':'Film workflow check','timeline':{'format':'16:9','sequence':{'format':'16:9','duration':0,'tracks':[]}}}])
            owner=await page.evaluate('''async ({sheet,room})=>{
                context={room_id:room,content_id:'film'};
                localStorage.setItem(consultationMemoKey({editContext:context}),JSON.stringify(sheet));
                return context;
            }''',{'sheet':sheet,'room':room})
            inputs=[];report=previous or {'owner':owner,'turns':[]}
            for row in report['turns']:
                inputs.extend([{'role':'user','content':row['input']},{'role':'assistant','content':row['reply']}])
            utterances=[
                'さっき決めた方向で。話の展開は全く決めてないから提案して。今は有料生成や全編制作はしないでね。',
                'その筋で良い。冒頭の作業場だけ、人物と機体の位置とカメラを動かして相談できる簡単な立体で見せて。ほかの場面は作らなくていい。',
                '人物を今より右へ動かして。カメラとか機体とか、ほかは変えなくていい。',
            ]
            for turn,text in enumerate(utterances):
                if turn<len(report['turns']):continue
                inputs.append({'role':'user','content':text});row={'input':text,'calls':[]};start=time.perf_counter()
                for _ in range(8):
                    response=await client.responses.create(model='gpt-6-astra',instructions=BACKEND_INSTRUCTIONS,
                        tools=tools(),input=inputs,reasoning={'effort':'low'},max_output_tokens=10000,store=False)
                    inputs.extend(x.model_dump(exclude_none=True) for x in response.output)
                    row['reply']=response.output_text
                    calls=[c for c in response.output if c.type=='function_call']
                    if not calls:break
                    for call in calls:
                        args=json.loads(call.arguments)
                        if call.name=='run_editor_task':
                            raise AssertionError('Unexpected production delegation for this unpaid editable preview')
                        result=await page.evaluate('''async c=>executeLiveConsultationTool(c,{id:'film-test',rows:{},editContext:context},context)''',
                            {'name':call.name,'call_id':call.call_id,'arguments':call.arguments})
                        row['calls'].append({'name':call.name,'arguments':args,'result':result})
                        inputs.append({'type':'function_call_output','call_id':call.call_id,'output':json.dumps(result,ensure_ascii=False)})
                row['seconds']=round(time.perf_counter()-start,2)
                report['turns'].append(row)
                (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                await page.screenshot(path=str(out/f'turn-{turn}.png'))
                print(turn,row['seconds'],[c['name'] for c in row['calls']],flush=True)
            assert any(c['name']=='update_film_plan' for c in report['turns'][0]['calls'])
            assert any(c['name']=='show_consultation_visual' and c['result'].get('shown') for c in report['turns'][1]['calls'])
            assert any(c['name']=='revise_consultation_visual' and c['result'].get('shown') for c in report['turns'][2]['calls'])
        finally:await browser.close()

if __name__=='__main__':asyncio.run(main())
