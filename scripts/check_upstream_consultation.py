"""Exercise the real consultation judge without opening or interrupting voice."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services import editor_consultation, editor_jev

CASES = [
    ('vague', {}, '動画を作りたいんだけど。', {'ask'}),
    ('film_reference', {}, '自宅の作業場で主人公が航空機を開発して実用化する、技術的に現実味のある映画を作りたい。', {'compare'}),
    ('launch_reference', {}, '新しい家計簿アプリのローンチ動画を作りたい。インスタで見て使ってみようと思ってほしい。雰囲気はまだ分からん。', {'compare'}),
    ('ready', {'brief':['家計簿アプリの紹介'], 'purpose':['インスタで利用を促す'], 'direction':['二本目の落ち着いた実写の雰囲気'], 'constraints':['30秒、アプリ画面を使う']}, '素材はさっき渡した画面だけで、人物は生成していい。', {'propose'}),
    ('missing_conditions', {'brief':['自宅で航空機を開発する映画'], 'direction':['二本目の温かい映画の感じ']}, 'そう、その感じが良い。', {'ask','select'}),
    ('question', {'brief':['映画'], 'direction':['温かい実写']}, 'ところでJevって何ができるん？今は参考を探さず説明だけして。', {'conversation'}),
    ('pivot', {'brief':['家計簿アプリ紹介'], 'purpose':['インスタで利用促進'], 'direction':['落ち着いた実写'], 'constraints':['30秒']}, 'やっぱ実写はやめて、勢いのある3Dの感じにしたい。どんなのがあるかな。', {'compare'}),
]

async def main():
    results=[]
    for name,facts,text,expected in CASES:
        dialogue=[{'role':'user','text':text}]
        memo={'version':2,'facts':facts}
        if '--route' in sys.argv:
            from app.services.editor_visual_decision import decide
            result=await decide('2582a188-ff24-4a4f-b989-6063034d90b2',dialogue,
                                include_url_index=True,consultation_memo=memo)
            updated=result['consultation_memo']
        else:
            result=await editor_jev.judge('2582a188-ff24-4a4f-b989-6063034d90b2',
                {'conversation':dialogue,'current_user_statement':text,'consultation_memo':memo},
                editor_consultation.questions(dialogue,memo),timeout=5)
            updated=editor_consultation.update(memo,dialogue,result.get('answers',{}))
        passed=result.get('available') and updated['next'] in expected
        if '--route' in sys.argv:
            passed=passed and not result.get('needs_backend')
            if expected=={'compare'}:passed=passed and bool(result.get('selected_library_ids'))
        results.append({'case':name,'input':text,'expected':sorted(expected),'passed':bool(passed),'memo':updated,**result})
        print(json.dumps({'case':name,'passed':bool(passed),'next':updated['next'],'ms':result['elapsed_ms'],'selected':result.get('selected_library_ids')},ensure_ascii=False),flush=True)
    path=ROOT/'scratch/upstream-consultation-20260922'/('route.json' if '--route' in sys.argv else 'results.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if all(r['passed'] for r in results) else 1

if __name__=='__main__':sys.exit(asyncio.run(main()))
