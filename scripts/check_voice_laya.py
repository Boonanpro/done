"""Local-only Laya multilingual evaluation against the production Jev question schema.
Install laya==0.4.15 and scipy==1.14.1 in the worktree venv, never Dan's runtime.
Synthetic Japanese cases declared before measurement; no threshold fitting.
"""
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.voice_prefetch import ASK, KINDS

CASES = [
    ('明日の尼崎の天気って','search'), ('今のドル円はいくら','search'),
    ('大阪城の開館時間を','search'), ('最新のアイフォンの値段','search'),
    ('京都の紅葉の見頃を','search'), ('今週末の大阪のイベント','search'),
    ('明日の予定を教えて','read'), ('今の作業はどうなってる','read'),
    ('この部屋にあるファイルは','read'), ('さっきのパソコンの相談、何を決めた','read'),
    ('昨日送ったメールの返事は来た','read'), ('保存した住所を教えて','read'),
    ('パン屋のホームページを作って','work'), ('紹介動画を作って','work'),
    ('この表の計算を直して','work'), ('明日の朝にリマインドを入れて','work'),
    ('メールの下書きを作って','work'), ('この写真を明るくして','work'),
    ('ありがとう、助かった','talk'), ('やっぱりやめておく','talk'),
    ('パソコンを買おうか迷ってる','talk'), ('今日は疲れたね','talk'),
    ('いや、それは頼んでいない','talk'), ('うん、その考えはいいね','talk'),
    ('あのさ','wait'), ('えーっと','wait'), ('なんだっけ','wait'),
    ('そういえば','wait'), ('その、あれを','wait'), ('ちょっとね','wait'),
]


def main():
    from laya import Router
    router = Router(device='mps')
    questions = {'kind':{'type':'choice','criteria':KINDS,'instructions':ASK}}
    before = time.perf_counter()
    router.predict({'utterance_so_far':'準備'},questions,model='multilingual')
    cold = time.perf_counter()-before
    rows=[]
    for text,expected in CASES:
        before=time.perf_counter()
        result=router.predict({'utterance_so_far':text},questions,model='multilingual')
        answer=result['answers']['kind']
        rows.append(dict(text=text,expected=expected,choice=answer['choice'],correct=answer['choice']==expected,
                         ms=round((time.perf_counter()-before)*1000,2),probabilities=answer['probabilities']))
    output=dict(device='mps',package='laya 0.4.15',cold_s=round(cold,3),correct=sum(r['correct'] for r in rows),
                total=len(rows),median_ms=statistics.median(r['ms'] for r in rows),rows=rows)
    path=ROOT/'.tmp/voice-early/laya.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in output.items() if k!='rows'},ensure_ascii=False))


if __name__=='__main__':main()
