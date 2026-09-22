"""Resumable URL-only collection and metadata classification; no video downloads.

Search provenance is never treated as proof of a video's style. Publication
merges the latest index, preserving observations and concurrent additions.
"""
import argparse, asyncio, collections, concurrent.futures, datetime, hashlib, json, re, sys
from pathlib import Path
import yt_dlp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_reference_url_pilot import GROUPS, Quiet
from scripts.label_reference_url_pilot import GENRES, USER
from app.services.editor_jev import judge

OUT = ROOT / 'scratch/reference-library-scale'
INDEX = ROOT / 'docs/reference-index/videos.json'
EXTRA = {
 'film_trailer': ['science fiction drama official trailer', 'romantic comedy official trailer', 'historical war movie official trailer', '日本映画 予告編 公式', 'thriller horror official trailer'],
 'animation_short': ['日本 アニメ 短編 公式', '自主制作 アニメ 短編 2D', 'stop motion animated short film official', 'hand drawn animated short film Gobelins', 'anime comedy official trailer', '中国 アニメ 短編 公式'],
 'tutorial': ['After Effects motion design tutorial', 'DaVinci Resolve filmmaking tutorial', '料理 DIY チュートリアル', 'Blender cinematography tutorial'],
 'production_breakdown': ['VFX breakdown official studio', '映画 メイキング 撮影 解説', 'motion design breakdown behind the scenes'],
 'reaction_review': ['camera review video', '映画 レビュー 解説', 'technology review smartphone'],
 'news_commentary': ['ニュース 解説 公式', 'visual journalism investigation official'],
 'gaming': ['game cinematic launch trailer official', 'ゲーム 実況 動画', 'esports highlight official'],
 'architecture': ['architectural film house tour official', '建築 ルームツアー 映像'],
 'event': ['concert live performance official', 'conference keynote opening film', '結婚式 オープニング ムービー'],
 'interview': ['documentary interview portrait film', '対談 インタビュー 公式'],
 'ambient': ['nature ambient slow cinema film', 'ASMR cinematic video'],
 'education': ['history visual explanation animated', '語学 教育 動画 公式'],
}
TAXONOMY = {**GENRES, **{k:k.replace('_',' ') for k in EXTRA}}

def save(path, value):
 path.parent.mkdir(parents=True, exist_ok=True)
 temp = path.with_suffix(path.suffix + '.tmp')
 temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
 temp.replace(path)

def collect(task):
 group, query, count = task
 digest = hashlib.sha256(f'{query}|{count}'.encode()).hexdigest()[:20]
 path = OUT / 'searches' / (digest + '.json')
 if path.exists():
  old = json.loads(path.read_text(encoding='utf8'))
  if not old.get('error'): return old
 try:
  options = dict(quiet=True, logger=Quiet(), extract_flat='in_playlist', skip_download=True, socket_timeout=15, retries=1)
  with yt_dlp.YoutubeDL(options) as client:
   result = client.extract_info(f'ytsearch{count}:{query}', download=False)
  rows = [{k:r.get(k) for k in ('id','title','channel','channel_id','duration','view_count','description','thumbnails')}
          for r in result.get('entries',[]) if r and re.fullmatch(r'[\w-]{11}', r.get('id') or '')]
  data = dict(group=group, query=query, retrieved_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), entries=rows)
 except Exception as exc:
  data = dict(group=group, query=query, entries=[], error=type(exc).__name__)
 save(path, data)
 print('search', group, len(data['entries']), data.get('error',''), flush=True)
 return data

async def run(args):
 groups = {k:list(v) for k,v in GROUPS.items()}
 for k,v in EXTRA.items(): groups.setdefault(k,[]).extend(v)
 tasks = [(g,q,args.per_query) for g,queries in groups.items() for q in queries]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  results = list(pool.map(collect,tasks))
 unique = {}
 for result in results:
  for row in result['entries']:
   item = unique.setdefault(row['id'], {**row, 'retrieved_at':result['retrieved_at'], 'groups':[], 'queries':[]})
   if result['group'] not in item['groups']: item['groups'].append(result['group'])
   if result['query'] not in item['queries']: item['queries'].append(result['query'])
 save(OUT/'candidates.json',list(unique.values()))
 existing = json.loads(INDEX.read_text(encoding='utf8'))
 old_ids = {r['video_id'] for r in existing['references']}
 fresh = [r for r in unique.values() if r['id'] not in old_ids]
 print('unique',len(unique),'new',len(fresh),flush=True)
 if args.collect_only: return
 sem = asyncio.Semaphore(3)
 async def classify(rows):
  digest = hashlib.sha256(json.dumps([TAXONOMY,rows],sort_keys=True).encode()).hexdigest()
  path = OUT/'labels'/(digest+'.json')
  if path.exists():
   result=json.loads(path.read_text(encoding='utf8'))
   if result.get('available'): return rows,result
  async with sem:
   questions = {r['id']:{'type':'choice', 'instructions':
    'Classify ONLY video '+r['id']+' using its title, publisher and description. Search groups are discovery hints, NOT evidence. '
    'A tutorial about a film is tutorial, not a narrative film. Never infer visual style or quality. Use other when uncertain.',
    'criteria':TAXONOMY} for r in rows}
   result = await judge(USER, {'videos':[{k:r.get(k) for k in ('id','title','channel','description')} for r in rows]}, questions, timeout=25)
   save(path,result)
   print('labels',len(rows),result.get('available'),flush=True)
   return rows,result
 labeled = await asyncio.gather(*(classify(fresh[i:i+12]) for i in range(0,len(fresh),12)))
 # Re-read immediately before merging; never replace existing annotations.
 manifest = json.loads(INDEX.read_text(encoding='utf8'))
 by_id = {r['id']:r for r in manifest['references']}
 before = len(by_id); failed = 0
 for rows,result in labeled:
  for r in rows:
   answer = result.get('answers',{}).get(r['id'],{})
   probabilities = answer.get('probabilities',{})
   genre = answer.get('choice')
   if not result.get('available') or genre not in TAXONOMY:
    failed += 1
    continue
   by_id.setdefault('yt-'+r['id'], dict(id='yt-'+r['id'],video_id=r['id'],url='https://www.youtube.com/watch?v='+r['id'],
    title=r['title'],publisher=r.get('channel') or '',publisher_id=r.get('channel_id'),duration_seconds=r.get('duration'),
    views_at_discovery=r.get('view_count'),retrieved_at=r['retrieved_at'],description_excerpt=r.get('description') or '',
    thumbnail_url=(r.get('thumbnails') or [{}])[-1].get('url'),
    labels=dict(primary_genre=genre,genre_probabilities=probabilities,medium='unknown',taste=[]),
    label_basis='publisher_search_metadata',visual_inspection='not_performed',embed_status='unchecked',
    availability='found_in_youtube_search',reference_uses=['creative_reference'],discovery=dict(groups=r['groups'],queries=r['queries'])))
 manifest.update(references=list(by_id.values()), count=len(by_id), updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
 save(INDEX,manifest)
 report=dict(before=before,after=len(by_id),added=len(by_id)-before,unclassified=failed,
  search_failures=sum(bool(r.get('error')) for r in results),genres=dict(collections.Counter(r['labels']['primary_genre'] for r in by_id.values())),
  caveat='Metadata classification only. No claim of visual inspection, quality approval or verified playback.')
 save(OUT/'report.json',report)
 print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser()
 parser.add_argument('--per-query',type=int,default=70)
 parser.add_argument('--collect-only',action='store_true')
 asyncio.run(run(parser.parse_args()))
