"""Compare identical real requests with full and multi-family retrieval."""
import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.services.reference_url_index import search,catalog

CASES=[
 'AIのローンチ動画。個人で仕事している人に便利そうと思ってほしい。雰囲気はまだ分からない。',
 'AIの紹介だけど広告っぽくなく、普通の部屋で人が働いている静かな実写がいい。',
 'やっぱり宇宙っぽい3Dで勢いがある動画にしたい。AIの紹介という目的はそのまま。',
 '字幕をかっこよく動かす編集方法を解説するYouTube動画を作りたい。',
 '結婚式で流す、ちょっと笑える二人の思い出のアニメーション。',
 '料理の手元を中心にした、落ち着いた縦の動画。',
]

async def main():
 out=ROOT/'scratch/reference-routing';out.mkdir(exist_ok=True)
 results=[]
 catalog_rows={r['id']:r for r in catalog()}
 for n,query in enumerate(CASES*3):
  pair={}
  for mode in (('full','genres') if n%2==0 else ('genres','full')):
   pair[mode]=await search('2582a188-ff24-4a4f-b989-6063034d90b2',query,routing=mode,embedded=True)
  full={r['id'] for r in pair['full']['results']};routed={r['id'] for r in pair['genres']['results']}
  route=pair['genres']['routing'];families=set(route.get('genres',[]))
  retained=full if route.get('mode')=='full' or route.get('fallback') else {
   ident for ident in full if catalog_rows[ident]['labels']['primary_genre'] in families or
   any(v>=.01 and g in families for g,v in catalog_rows[ident]['labels']['genre_probabilities'].items())}
  row={'query':query,**pair,'result_overlap':len(full&routed)/len(full) if full else None,
       'full_results_retained_by_route':len(retained),'full_result_count':len(full)}
  results.append(row)
  (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
  print(json.dumps({'case':n,'ms':{m:r['elapsed_ms'] for m,r in pair.items()},
   'candidates':pair['genres']['candidate_count'],'routing':pair['genres']['routing'],
   'overlap':row['result_overlap']},ensure_ascii=True),flush=True)
if __name__=='__main__':asyncio.run(main())
