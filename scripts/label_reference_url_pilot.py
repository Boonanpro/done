"""Coarse metadata-only labeling. Never claim a video was watched here."""
import asyncio,collections,json,hashlib,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.services.editor_jev import judge
from scripts.build_reference_url_pilot import GROUPS
OUT=ROOT/'scratch/reference-url-pilot'
USER='2582a188-ff24-4a4f-b989-6063034d90b2'
GENRES={**{g:g.replace('_',' ') for g in GROUPS},
 'tutorial':'How-to, practical tutorial or step-by-step instruction',
 'production_breakdown':'Behind the scenes or explanation of how a work was made',
 'reaction_review':'Reaction, opinion or product/work review',
 'news_commentary':'News or commentary about events or products',
 'compilation':'Compilation, ranking or curated collection',
 'other':'Other purpose or cannot establish from available metadata'}

async def main():
 rows=json.loads((OUT/'candidates.json').read_text(encoding='utf8'))
 # Retain every unique URL. Duration, popularity and format are attributes,
 # not eligibility gates. Tutorials can be creative references themselves.
 (OUT/'labels-v2').mkdir(exist_ok=True)
 sem=asyncio.Semaphore(4)
 async def batch(n,group):
  digest=hashlib.sha256(json.dumps(group,sort_keys=True).encode()).hexdigest()[:16]
  path=OUT/'labels-v2'/f'{n:03}-{digest}.json'
  if path.exists():return json.loads(path.read_text(encoding='utf8'))
  async with sem:
   state={'videos':{r['id']:{k:r.get(k) for k in ('title','channel','description','duration','discovery_groups')} for r in group}}
   questions={}
   for row in group:
    ident=row['id']
    questions['genre_'+ident]={'type':'choice','instructions':
      'Classify video '+ident+' using its title, publisher and description only. Discovery groups are retrieval hints, not truth. '
      'All formats are valid references, INCLUDING tutorials, production breakdowns, reactions, news and compilations. '
      'Classify the video itself, not the work it discusses: a review of an AI launch is reaction_review, a launch film is ai_launch. '
      'Prefer a concrete purpose/genre over surface keywords. Use other for uncertainty, never exclude the item.',
      'criteria':GENRES}
    questions['medium_'+ident]={'type':'choice','instructions':'For '+ident+', what medium is explicitly supported by title or description? Do not guess from publisher or genre. unknown if not evidenced.',
      'criteria':{'live_action':'Live action explicitly evidenced','animation':'Animation explicitly evidenced','motion_graphics':'Motion graphics or animated typography explicitly evidenced','mixed':'Mixed media explicitly evidenced','unknown':'Cannot establish from metadata'}}
   result=await judge(USER,state,questions,timeout=20)
   path.write_text(json.dumps({'ids':[r['id'] for r in group],**result},ensure_ascii=False,indent=2),encoding='utf8')
   print('batch',n,result.get('available'),result.get('elapsed_ms'),flush=True)
   return json.loads(path.read_text(encoding='utf8'))
 batches=await asyncio.gather(*(batch(n,rows[i:i+12]) for n,i in enumerate(range(0,len(rows),12))))
 answers={k:v for b in batches for k,v in b.get('answers',{}).items()}
 labeled=[]
 for r in rows:
  a=answers.get('genre_'+r['id'],{});genre=a.get('choice');p=a.get('probabilities',{}).get(genre,0)
  m=answers.get('medium_'+r['id'],{});medium=m.get('choice','unknown')
  if m.get('probabilities',{}).get(medium,0)<.8:medium='unknown'
  labeled.append({**r,'genre':genre or 'other','genre_probability':p,'genre_probabilities':a.get('probabilities',{}),
    'medium':medium,'label_basis':'publisher_search_metadata','visual_inspection':'not_performed','taste_labels':[],
    'reference_uses':['creative_reference']+(['production_learning'] if genre in ('tutorial','production_breakdown') else [])})
 (OUT/'labeled-all.json').write_text(json.dumps(labeled,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps({'labeled':len(labeled),'genres':dict(collections.Counter(r['genre'] for r in labeled))}),flush=True)

if __name__=='__main__':asyncio.run(main())
