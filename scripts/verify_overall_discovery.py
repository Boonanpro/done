import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.services.editor_visual_decision import decide

async def main():
    root=ROOT/'uploads/production-assets/e47f056e-77b1-4e39-9173-4a01dfadbc03/assistant/events'
    source=next(root.glob('*.jsonl'));turns={}
    for line in source.read_text(encoding='utf8').splitlines():
        r=json.loads(line)
        if r.get('type') in ('user_transcript','assistant_transcript'):turns[r['item_id']]=r
    dialogue=[];cases=[]
    for r in sorted(turns.values(),key=lambda r:r.get('start_ms',0)):
        dialogue.append({'role':'user' if r['type']=='user_transcript' else 'assistant','text':r['text']})
        if r['type']=='user_transcript' and len(r['text'])>80:cases.append(list(dialogue))
    cases += [[{'role':'user','text':text}] for text in [
        '新しい家計簿アプリを使ってみたくなる広告を作りたい。Instagramに出す。雰囲気は実物を見て決めたい。',
        'YouTubeで初心者に料理を教える動画を作りたい。どんな見せ方が良いか参考を見て考えたい。']]
    out=ROOT/'scratch/overall-discovery';out.mkdir(exist_ok=True)
    results=[]
    for n,d in enumerate(cases):
        value=await decide('2582a188-ff24-4a4f-b989-6063034d90b2',d,include_url_index=True)
        results.append({'dialogue':d,'result':value})
        (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'case':n,'action':value['action'],'ids':value['selected_library_ids'],'ms':value['elapsed_ms'],
                          'beliefs':(value.get('discovery') or {}).get('beliefs')},ensure_ascii=True),flush=True)
if __name__=='__main__':asyncio.run(main())
