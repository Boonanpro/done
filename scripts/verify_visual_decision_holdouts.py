"""Additional routing/selection checks; expected IDs never enter the model state."""
import asyncio,json,sys,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.editor_visual_decision import decide

CASES=[
 ('topic_switch', ['字幕は細い明朝で金色がいい。','それとは別で、世界各国の売上の違いを色で見せたい。参考の見た目はどんなのがある？'], 'compare', {'hf-world-map'}),
 ('chart', ['数字の一覧だと退屈なので、棒と線が順番に出て成長が伝わるものを見たい。'], 'compare', {'hf-data-chart'}),
 ('camera', ['場面をパッと切るより、カメラを横に勢いよく振って次の場面につながる感じが気になる。'], 'compare', {'hf-whip-pan'}),
 ('real_car', ['車の中で仕事している生活を映画っぽく見せたい。CGより実際の人物を撮ったような参考がいい。'], 'compare', {'stock-car'}),
 ('retained_preference', ['実写ではなく少し絵みたいな感じ。ただし子供向けのにぎやかなアニメは違います。',
     {'role':'assistant','text':'実写や子供向けの参考もいいと思います。'},
     '暖かい光の室内で人が静かに話している表情を見たい。'], 'compare', {'film-sintel-dialogue'}),
 ('process_feedback', ['参考は良いけど表示の仕方が分かりにくいと思う。今すぐ動画を作ってという意味ではないよ。'], 'talk', set()),
 ('silence', ['少し考えるので返事せず待って。'], 'listen', set()),
 ('hypothetical', ['もし方向性が決まったら、その後どう進めるといいと思う？'], 'talk', set()),
 ('explicit_timeline', ['さっきの絵コンテをタイムラインに並べて、30秒で通して見られるようにして。'], 'execute', set()),
]

async def main():
    results=[]
    for name,words,action,targets in CASES:
        result=await decide('2582a188-ff24-4a4f-b989-6063034d90b2',[w if isinstance(w,dict) else {'role':'user','text':w} for w in words])
        row={'case':name,'words':words,**result}
        row['passed']=result['action']==action and (not targets or bool(targets.intersection(result['selected_library_ids'])))
        if name=='retained_preference':
            row['passed']=row['passed'] and not {'film-tears-human','film-bunny-comedy'}.intersection(result['selected_library_ids'])
        results.append(row)
        print(json.dumps({k:row[k] for k in ('case','passed','action','selected_library_ids','elapsed_ms')},ensure_ascii=False),flush=True)
    Path(os.environ.get('DAN_TEST_RESULT','scratch/visual-decision/holdouts.json')).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    if not all(r['passed'] for r in results):raise SystemExit(1)

asyncio.run(main())
