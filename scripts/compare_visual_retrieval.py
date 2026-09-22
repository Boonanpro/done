"""Shadow both Jev question layouts on identical unseen dialogs; no UI mutations."""
import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.editor_visual_decision import decide

async def main():
    rows=[]
    for name in ('caption','motion','film'):
        data=json.loads((Path('scratch/visual-acceptance-final')/name/'final.json').read_text(encoding='utf8'))
        dialogue=[]
        for entry in data['messages']:
            dialogue.append({'role':entry['role'],'text':entry['text']})
            if entry['role']!='user':continue
            result=await decide('2582a188-ff24-4a4f-b989-6063034d90b2',dialogue,retrieval='choice')
            rows.append({'case':name,'text':entry['text'],**result})
            print(json.dumps({k:rows[-1][k] for k in ['case','action','elapsed_ms','selected_library_ids','coverage_missing']},ensure_ascii=False),flush=True)
    Path('scratch/visual-decision/choice-retrieval.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')

asyncio.run(main())
