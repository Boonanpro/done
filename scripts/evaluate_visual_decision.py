"""Real Jev routing checks. No production edits, no voice connection."""
import asyncio,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.editor_visual_decision import decide

CASES=[
 ('cinema','5分くらいの映画を作りたい。自然の中で自由に暮らして、都会では仕事もする理想の生活。テイストはまだ言葉にできない。','compare'),
 ('caption','字幕の見た目が分からない。高級感は欲しいけど、堅すぎない感じがいい。','compare'),
 ('critique','絵の雰囲気はいい。ただ絵コンテなら本来タイムラインに並ぶものだと思う。今すぐやってと言ってるわけじゃない。','talk'),
 ('silence','黙って。それすら返事しないで。','listen'),
 ('approval_question','仮にこれが合格だとしたら、次は何をするのが良いと思う？','talk'),
 ('timeline','この16場面を順番と尺が分かるようにタイムラインへ並べて。','execute'),
 ('motion','サービスの紹介を作りたい。説明くさいより、文字や画面が気持ちよく動いてワクワクするやつ。','compare'),
 ('acknowledgment','うん','listen'),
]

async def main():
 out=Path('scratch/visual-decision');out.mkdir(parents=True,exist_ok=True)
 results=[]
 for name,text,expected in CASES:
  r=await decide('2582a188-ff24-4a4f-b989-6063034d90b2',[{'role':'user','text':text}])
  results.append({'case':name,'utterance':text,'expected':expected,**r})
  print(json.dumps({k:results[-1][k] for k in ['case','action','expected','elapsed_ms','selected_library_ids','coverage_missing']},ensure_ascii=False),flush=True)
  (out/'routing.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
 print('correct',sum(r['action']==r['expected'] for r in results),'/',len(results))

asyncio.run(main())
