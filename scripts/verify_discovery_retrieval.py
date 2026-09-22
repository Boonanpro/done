"""Actual Jev + actual URL catalog; save evidence rather than claiming narrowing."""
import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.services.editor_visual_decision import decide
from app.services.reference_url_index import presentation_rows
from scripts.verify_discovery_pivots import CASES

async def main():
 rows=[]
 for name,dialogue in [('initial',[{'role':'user','text':'ダンっていうAIのローンチ動画を作りたい。個人で仕事してる人向けにYouTubeに出す。何ができるか見て使いたくなる感じ。テイストはまだ分からんから実物を見て考えたい。'}]),
                      ('pivot',CASES[1][1])]:
  r=await decide('2582a188-ff24-4a4f-b989-6063034d90b2',dialogue,include_url_index=True)
  rows.append({'case':name,'result':r})
  d=r.get('discovery') or {}
  print(json.dumps({'case':name,'action':r['action'],'ids':r['selected_library_ids'],'ms':r['elapsed_ms'],
    'next':d.get('next_axis'),'reason':d.get('comparison',{}).get('reason'),'sides':d.get('comparison',{}).get('sides')},ensure_ascii=False),flush=True)
 out=ROOT/'scratch/discovery-pivots/retrieval.json';out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':asyncio.run(main())
