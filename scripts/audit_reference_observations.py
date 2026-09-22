"""Independent second viewing of a small sample; never silently rewrites evidence."""
import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.services.video_analyzer import analyze_video_url
from scripts.inspect_discovery_references import parse_observation

async def main():
 gate=asyncio.Semaphore(3)
 async def one(ident):
  record=json.loads((ROOT/f'scratch/discovery-observations/{ident}.json').read_text(encoding='utf8'))
  prompt=('動画を独立に視聴して添付の観察記録を監査してください。記録を正しいと仮定しない。'
   '特に実写/CGの区別、人物の有無、音声、秒数を確認。制作ソフトは推測しない。'
   'JSONだけ: {"accessible":true,"observations":[],"supported":trueまたはfalse,'
   '"issues":[具体的な誤り],"checked":"何を確認できたか"}。見られない場合accessible:false。記録:\n'
   +json.dumps(record,ensure_ascii=False))
  async with gate:text=await analyze_video_url('youtube',ident,record['source_url'],prompt)
  result=parse_observation(text or '')
  print(ident,result.get('supported'),flush=True)
  return {'id':ident,'audit':result}
 results=await asyncio.gather(*(one(i) for i in ['2gYqEi8-am4','bj17iQDGZeA','5Sa9nYKiYg0','CwmKr-wkj1M','uFk0mgljtns']))
 (ROOT/'scratch/discovery-observations/audit-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':asyncio.run(main())
