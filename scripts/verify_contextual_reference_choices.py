"""Purpose and feedback tests: expected IDs are never sent to Jev."""
import asyncio,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.editor_visual_decision import decide

CASES=[
 ('reflective',[
  '仕事に追われていた自分が暮らしを見直すYouTube動画です。同じように疲れた人に肩の力を抜いてほしい。',
  '映像は静かな日常の実写。字幕も落ち着いて気持ちを語る感じにしたい。文字だけの黒背景じゃなく、映像と一緒に見て選びたい。'],{'dan-caption-reflective','dan-caption-clear'}),
 ('clear',[
  '初心者にコーヒーの淹れ方を説明する動画です。',
  '字幕は詩みたいな雰囲気じゃなくて、話がすっと入ってくる読みやすいものがいい。飛び跳ねる文字やカラオケみたいなのは違う。映像に乗ってる例ある？'],{'dan-caption-clear'}),
 ('emphasis',[
  'カフェの短いインスタ動画で、忙しい日にも休んでいいんだと思ってもらいたい。',
  '全部の言葉を同じにせず、ひと言だけぱっと印象に残る字幕の見せ方がいい。でも派手な点滅や絵文字はなし。実写と合わせた見本で見たい。'],{'dan-caption-emphasis'}),
 ('changed',[
  '派手なゲーム広告の飛び出す文字がいい。',
  'やっぱり別件です。自分の日常を静かに振り返るVlogで、字幕は控えめに語りかけるようにしたい。実写の上に出る例を見たい。'],{'dan-caption-reflective','dan-caption-clear'}),
 ('rejected',[
  '日常のVlogです。字幕は自然に馴染ませたい。',
  {'role':'assistant','text':'大きく跳ねる文字が良さそうです。'},
  'そうじゃなくて、映像の空気を邪魔しないでほしい。少し本を読んでいるみたいな余韻のある感じが近いかな。'],{'dan-caption-reflective'}),
]

async def main():
    rows=[]
    for name,words,expected in CASES:
        result=await decide('2582a188-ff24-4a4f-b989-6063034d90b2',[w if isinstance(w,dict) else {'role':'user','text':w} for w in words])
        passed=result['action']=='compare' and bool(expected.intersection(result['selected_library_ids']))
        rows.append({'case':name,'dialogue':words,'expected':sorted(expected),'passed':passed,**result})
        print(json.dumps({'case':name,'passed':passed,'ids':result['selected_library_ids'],'ms':result['elapsed_ms']},ensure_ascii=False),flush=True)
    out=Path('scratch/purpose-intake')/f'caption-choices-{int(time.time())}.json'
    out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    if not all(x['passed'] for x in rows):raise SystemExit(1)

asyncio.run(main())
