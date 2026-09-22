import asyncio,json,math,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.services.reference_url_index import search,catalog
CASES=[
 ('ai_launch','work','AIモデルのローンチ動画を作りたい。発表映像そのものを見比べたい。解説者のレビューではなく。',{'ai_launch'}),
 ('software','work','SaaSの新サービスを発表するローンチ動画を見比べたい。',{'software_launch','ai_launch'}),
 ('tutorial','work','After Effectsでモーショングラフィックスを教えるチュートリアル動画を作りたい。教え方の参考を見せて。',{'tutorial'}),
 ('behind','work','CMの撮影や合成の裏側を説明するメイキング動画を自分も作りたい。参考になる作品を見たい。',{'production_breakdown'}),
 ('vlog','work','自宅の日常や料理を見せる静かなVlogの参考がほしい。',{'vlog','food'}),
 ('charity','work','社会問題を伝えて支援を呼びかけるキャンペーン映像の参考がほしい。',{'social_impact','brand_film'}),
 ('history','technique','過去の古い映像と現代の映像を対比して、進化を感じさせる導入を見たい。',{0.0,9.2}),
 ('physical','technique','画面の中で作ったものが最後に現実の物体になって出てくる場面を見たい。',{149.0,153.2,156.5}),
 ('title','technique','カメラが引いて大きな製品名のタイトルを出す演出を見たい。',{39.5}),
 ('absent','technique','宇宙から地球へ近づき、世界の都市を光の線で結ぶ実際のカットを見たい。',set()),
]
async def main():
 genre={r['id']:r['labels']['primary_genre'] for r in catalog()};results=[]
 for name,scope,query,expected in CASES:
  result=await search('2582a188-ff24-4a4f-b989-6063034d90b2',query,scope=scope)
  found=result['results'];top=found[0] if found else None
  passed=(not found) if not expected else bool(top and ((genre.get(top['id']) in expected) if scope=='work' else top.get('start') in expected))
  row={'case':name,'scope':scope,'query':query,'passed':result['available'] and passed,**result};results.append(row)
  print(json.dumps({'case':name,'passed':row['passed'],'ms':result['elapsed_ms'],'top':top},ensure_ascii=True),flush=True)
  (ROOT/'scratch/reference-url-pilot/retrieval-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
 print('passed',sum(r['passed'] for r in results),'of',len(results))

if __name__=='__main__':asyncio.run(main())
