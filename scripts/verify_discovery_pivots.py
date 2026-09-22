"""Real Jev only. User-like corrections; expected beliefs never enter requests."""
import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.services import editor_discovery as discovery,editor_jev

BASE=[{'role':'user','text':'一人で仕事してる人に、ダンを使うとこんなことできるんだって伝えるローンチ動画を作りたい。YouTubeに出す。'},
 {'role':'assistant','text':'実写の日常を見せる感じと、文字や図で勢いよく見せる感じでは、どちらが近いですか？'},
 {'role':'user','text':'実写が近いかな。静かで普通の部屋みたいなの。でも綺麗すぎる暮らしは違う。'}]
CASES=[
 ('refine',BASE+[{'role':'user','text':'うん。人の顔ばっかりじゃなくて手元とか、何やってるかが見える方がいい。静かな感じはそのままで。'}],{'tone':'calm','setting':'ordinary','focus':'action'},'refine'),
 ('pivot_style',BASE+[{'role':'user','text':'いや、やっぱ全然違う方向にしたい。実写じゃなくて3Dアニメ。めっちゃ勢いがあって、宇宙みたいな非日常の世界がいい。ダンの紹介って目的は変わらんけど。'}],{'medium':'animation_3d','setting':'fantasy','tone':'energetic'},'pivot'),
 ('hypothetical',BASE+[{'role':'user','text':'派手な3Dアニメも作れるん？って聞いただけ。そっちにするとは言ってないからね。'}],{'medium':'live','setting':'ordinary','tone':'calm'},'none'),
 ('pivot_back',BASE+[{'role':'user','text':'やっぱ3Dアニメで宇宙っぽくしたい。勢いある感じ。'},
 {'role':'assistant','text':'非日常の3Dに変えるんですね。'},
 {'role':'user','text':'ごめん、やっぱ最初の実写に戻すわ。でも静かな感じじゃなくて笑える感じにしたい。普通の部屋で起きるコントみたいな。'}],{'medium':'live','setting':'ordinary','tone':'playful'},'pivot'),
 ('pivot_purpose',BASE+[{'role':'user','text':'ダンの紹介はいったんやめるわ。友達の結婚式で流す動画を作りたい。二人の思い出を物語にして、楽しくて笑える2Dアニメにしたい。'}],{'medium':'animation_2d','form':'story','tone':'playful'},'pivot'),
]
async def main():
 rows=[]
 for name,dialogue,expected,change in CASES:
  result=await editor_jev.judge('2582a188-ff24-4a4f-b989-6063034d90b2',{'conversation':dialogue},discovery.questions(),timeout=5)
  plan=discovery.plan(result.get('answers',{}))
  passed=bool(plan and all(plan['beliefs'][k]['preferred']==v for k,v in expected.items()) and plan['change']==change)
  rows.append({'case':name,'passed':passed,'expected':expected,'plan':plan,'elapsed_ms':result['elapsed_ms'],'dialogue':dialogue})
  print(json.dumps({'case':name,'passed':passed,'ms':result['elapsed_ms'],'plan':plan},ensure_ascii=False),flush=True)
 out=ROOT/'scratch/discovery-pivots';out.mkdir(exist_ok=True)
 (out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
 if not all(r['passed'] for r in rows):raise SystemExit(1)
if __name__=='__main__':asyncio.run(main())
