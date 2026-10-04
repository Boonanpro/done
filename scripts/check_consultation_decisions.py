"""Actual backend decisions with fixed consultation state; not a voice test."""
import asyncio,json
from pathlib import Path
from openai import AsyncOpenAI
from app.config import settings
from app.services.editor_consultation_sheet import tools,BACKEND_INSTRUCTIONS,empty

async def main():
    client=AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    cases=[('visual','その構成、言葉だけだと想像できない。恐竜の生活から化石の説明、もう一度生活に戻る流れってどういうこと？本編はまだ作らないで。'),
           ('refine','さっきの自然ドキュメンタリーの臨場感は近い。でも生き物を観察するだけじゃなく、専門的なことを図解で面白く説明する感じが欲しい。')]
    results=[]
    for name,text in cases:
        inputs=[{'role':'user','content':text}]
        calls=[]
        for _ in range(3):
            r=await client.responses.create(model='gpt-6-astra',instructions=BACKEND_INSTRUCTIONS,input=inputs,
                tools=tools(),reasoning={'effort':'low'},max_output_tokens=4000,store=False)
            inputs.extend(x.model_dump(exclude_none=True) for x in r.output)
            functions=[x for x in r.output if x.type=='function_call']
            if not functions:break
            for call in functions:
                args=json.loads(call.arguments);calls.append({'name':call.name,'args':args})
                output={'saved':True,'sheet':empty()}
                if call.name=='get_consultation_state':output={'sheet':empty(),'displayed':[{'id':'penguin','title':'Natural documentary','kind':'video'}]}
                inputs.append({'type':'function_call_output','call_id':call.call_id,'output':json.dumps(output)})
            if any(x.name in ('show_consultation_visual','search_reference_library','run_editor_task') for x in functions):break
        results.append({'case':name,'calls':calls})
    out=Path('scratch/consultation-visual');out.mkdir(parents=True,exist_ok=True)
    (out/'decisions.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    for r in results:print(r['case'],[c['name'] for c in r['calls']])
    assert any(c['name']=='show_consultation_visual' for c in results[0]['calls'])
    assert not any(c['name']=='run_editor_task' for c in results[0]['calls'])
    assert any(c['name']=='search_reference_library' and c['args'].get('refinement',{}).get('change') for c in results[1]['calls'])
    await client.close()

if __name__=='__main__':asyncio.run(main())
