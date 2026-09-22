"""Read-only retrieval measurements. No voice sessions or production jobs."""
import asyncio,json,sys,time,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.services.reference_url_index import catalog,search

CASES=[
 ('launch','AIの新製品のローンチ動画を作りたい。発表映像そのものの参考を見せて。',[]),
 ('film','自宅の作業場で主人公が航空機を開発する、技術的に現実味のある映画を作りたい。全体の雰囲気が近い参考は？',[]),
 ('anime','将棋の駒が人間みたいに喋る、日常コメディの2Dアニメを作りたい。はたらく細胞みたいな方向で、粘土や3Dではない参考がほしい。',[]),
 ('tutorial','After Effectsの編集の仕方を教えるYouTube動画を作りたい。分かりやすい教え方の参考を見たい。',[]),
 ('pivot','やっぱりアニメはやめて、静かな実写の旅行Vlogにしたい。そっちの参考を見せて。',[{'role':'user','text':'将棋の駒を擬人化した2Dアニメを作りたい'}]),
 ('architecture','建築家が自分の住宅を紹介する落ち着いた映像を作りたい。参考を見たい。',[]),
]
async def main():
 rows=catalog(); timings=[]
 for _ in range(50):
  start=time.perf_counter();catalog();timings.append((time.perf_counter()-start)*1000)
 results=[]
 for name,query,dialogue in CASES:
  result=await search('2582a188-ff24-4a4f-b989-6063034d90b2',query,dialogue=dialogue,routing='genres',embedded=True,verify_matches=True)
  results.append(dict(case=name,query=query,**result))
  report=dict(reference_count=len(rows),cached_read_median_ms=statistics.median(timings),results=results)
  (ROOT/'scratch/reference-library-scale/retrieval-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
  print(json.dumps(dict(case=name,available=result['available'],ms=result['elapsed_ms'],candidate_count=result['candidate_count'],routing=result['routing'],titles=[r['title'] for r in result['results']]),ensure_ascii=False),flush=True)
if __name__=='__main__':asyncio.run(main())
