"""Experimental URL-only reference retrieval. No playback or editor mutations.

The full index is searchable; metadata-only observations stay explicitly marked.
"""
import asyncio,json,math,time
import httpx
from functools import lru_cache
from pathlib import Path
from app.services import editor_jev

ROOT=Path(__file__).resolve().parents[2]
INDEX=ROOT/'docs/reference-index/videos.json'
DEEP=ROOT/'docs/reference-index/openai-gpt6-astra.json'
OBSERVATIONS=ROOT/'docs/reference-index/visual-observations.json'
_availability_cache={}

async def unavailable_reference_ids(rows):
 """Reject confirmed oEmbed failures, not network uncertainty. No downloads."""
 semaphore=asyncio.Semaphore(4)
 async with httpx.AsyncClient(timeout=3) as client:
  async def check(row):
   url=row.get('url','')
   if not url.startswith(('https://www.youtube.com/watch?', 'https://youtu.be/')):return None
   cached=_availability_cache.get(url)
   if cached and time.monotonic()-cached[0]<900:return row['id'] if cached[1] else None
   async with semaphore:
    try:
     response=await client.get('https://www.youtube.com/oembed',params={'url':url,'format':'json'})
     if response.status_code not in (200,401,403,404):return None
     blocked=response.status_code!=200
     _availability_cache[url]=(time.monotonic(),blocked)
     return row['id'] if blocked else None
    except httpx.HTTPError:return None
  return {ident for ident in await asyncio.gather(*(check(r) for r in rows)) if ident}

@lru_cache(maxsize=6)
def _read_snapshot(path,mtime_ns,size):
 return json.loads(Path(path).read_text(encoding='utf8'))

def _read_json(path):
 stat=path.stat()
 return _read_snapshot(str(path),stat.st_mtime_ns,stat.st_size)

def observations():
 return _read_json(OBSERVATIONS) if OBSERVATIONS.exists() else {}

def catalog():
 # Atomic index replacement invalidates this process-local read-only cache.
 return _read_json(INDEX)['references']

def presentation_rows():
 observed=observations()
 return [{**r,'kind':'video','source_url':r['url'],'family':r['id'],
          'description':r['title']+' | '+r.get('publisher','')+' | '+r['labels']['primary_genre']+' | '+observed.get(r['id'],{}).get('summary',''),
          'limitations':['Model-observed video; embed availability unverified.' if r['id'] in observed else 'Metadata-based reference; unverified visual style and embed availability.']}
         for r in catalog()]

def observation_search_text(record, observation_index=None):
 """Search measured style facets without promoting reproduction guesses to fact."""
 parts=[]
 for axis,entries in record.get('facets',{}).items():
  labels=[e['label'] for e in entries if isinstance(e,dict) and isinstance(e.get('label'),str)
          and (observation_index is None or observation_index in e.get('observation_indices',[]))]
  if labels:parts.append(axis+': '+', '.join(labels[:3]))
 for technique in record.get('techniques',[]):
  if observation_index is None or technique.get('observation_index')==observation_index:
   parts.append('Observed technique: '+technique.get('name',''))
 return ' | '.join(parts)[:1400]

def candidates(scope='work'):
 if scope=='work':
  observed=observations()
  return [{**r,'search_text':' | '.join(filter(None,[r['title'],r.get('publisher'),r['labels']['primary_genre'],
    r['description_excerpt'][:160],'; '.join(r['labels']['taste']),
    'Video observation: '+observed[r['id']]['summary'] if r['id'] in observed else '',
    observation_search_text(observed.get(r['id'],{}))]))} for r in catalog()]
 if scope!='technique':raise ValueError('scope must be work or technique')
 detail=json.loads(DEEP.read_text(encoding='utf8'))
 segments=[{**s,'url':s['source_url'],'title':f"{s['start']:.1f}–{s['end']:.1f}s",'label_basis':s['observation_basis'],
  'search_text':' | '.join([s['visual'],s['camera'],s['editing'],s['audio'],'; '.join(s['search_labels'])])}
  for s in detail['segments']]
 for ident,observed in observations().items():
  for n,s in enumerate(observed.get('observations',[])):
   segments.append({**s,'id':f'{ident}-observation-{n}','parent_id':ident,
    'url':observed['source_url'],'title':f"{s['start']:.1f}–{s['end']:.1f}s",
    'label_basis':'model_video_observation',
    'search_text':' | '.join([s['visual'],s.get('motion',''),s['audio'],observation_search_text(observed,n)]),
    'techniques':[t for t in observed.get('techniques',[]) if t.get('observation_index')==n]})
 return segments

async def route_candidates(user_id,rows,state,timeout=8):
 """Experimental multi-path routing. Uncertainty retains full coverage."""
 genres=sorted({r.get('labels',{}).get('primary_genre') for r in rows}-{None})
 if not genres:return rows,{'mode':'full','reason':'missing_labels'}
 genre_question={'type':'choice',
  'instructions':'Choose useful reference families, considering BOTH purpose and desired visual treatment. '
  'For example a cinematic AI launch can use narrative films as well as launch videos. '
  'Distribute probability across all useful families, not only the subject category. '
  'Latest explicit changes override conflicting prior preferences. Hypotheticals do not. '
  'Choose broad when the intent is too uncertain to safely narrow families.',
  'criteria':{**{g:g.replace('_',' ') for g in genres},'broad':'Broad or uncertain; search every family'}}
 style_question={**genre_question,'instructions':
  'Select reference families for the desired VISUAL TREATMENT, independent of what is being advertised. '
  'For example space 3D can come from animation shorts, cinematic storytelling from narrative shorts, '
  'ordinary working people from documentary or vlog. Distribute mass across useful families. '
  'The request purpose must not suppress transferable visual references. '
  'Use broad if no visual preference is expressed. Latest actual preference overrides old ones, not hypotheticals.'}
 result=await editor_jev.judge(user_id,state,{'genres':genre_question,'visual_genres':style_question},timeout=timeout)
 p=result.get('answers',{}).get('genres',{}).get('probabilities',{})
 if not result.get('available') or not p or p.get('broad',0)>=.15:
  return rows,{'mode':'full','reason':'uncertain_or_unavailable','elapsed_ms':result.get('elapsed_ms')}
 selected=[];mass=0
 for g in sorted(genres,key=lambda g:-p.get(g,0)):
  if p.get(g,0)<=0:break
  selected.append(g);mass+=p.get(g,0)
  if len(selected)>=3 and mass>=.95:break
 selected=set(selected)
 style=result.get('answers',{}).get('visual_genres',{}).get('probabilities',{})
 if style and style.get('broad',0)<.15:
  style_mass=0;style_count=0
  for g in sorted(genres,key=lambda g:-style.get(g,0)):
   if style.get(g,0)<=0:break
   selected.add(g);style_mass+=style[g];style_count+=1
   if style_count>=2 and style_mass>=.95:break
 narrowed=[r for r in rows if r.get('labels',{}).get('primary_genre') in selected or
           any(g in selected for g in r.get('labels',{}).get('related_genres',[])) or
           any(v>=.1 and g in selected for g,v in r.get('labels',{}).get('genre_probabilities',{}).items())]
 if not narrowed or len(narrowed)>=len(rows)*.85:
  return rows,{'mode':'full','reason':'insufficient_reduction','elapsed_ms':result.get('elapsed_ms')}
 return narrowed,{'mode':'genres','genres':sorted(selected),'retained_mass':mass,
                  'elapsed_ms':result.get('elapsed_ms'),'usage':result.get('usage')}

def choice_batches(choices, max_items=200, max_bytes=24000):
 """Bound UTF-8 payload as well as choice count; Japanese scene notes are dense."""
 groups=[];group={};size=0
 for key,value in choices.items():
  cost=len(json.dumps({key:value},ensure_ascii=False).encode('utf8'))
  if group and (len(group)>=max_items or size+cost>max_bytes):
   groups.append(group);group={};size=0
  group[key]=value;size+=cost
 if group:groups.append(group)
 return groups

async def search(user_id,query,*,scope='work',limit=3,timeout=8,dialogue=(),embedded=False,displayed=(),discovery=None,routing='full',verify_matches=False):
 if not isinstance(query,str) or not query.strip():raise ValueError('query required')
 if not 1<=limit<=5:raise ValueError('limit must be 1..5')
 if routing not in ('full','genres'):raise ValueError('routing must be full or genres')
 started=time.perf_counter();rows=candidates(scope)
 if embedded:
  rows=[r for r in rows if r.get('embed_status')!='blocked_by_publisher' and
        r.get('availability') not in ('unavailable','private','deleted','expired','reported_unavailable')]
 total_count=len(rows);route={'mode':'full'}
 if routing=='genres' and scope=='work':
  rows,route=await route_candidates(user_id,rows,{'request':query,'conversation':list(dialogue)[-30:],
      'displayed':list(displayed)[-24:],'discovery':discovery},timeout)
 criteria={r['id']:r['search_text'] for r in rows}
 async def judge_choices(choices):
  return await editor_jev.judge(user_id,{'request':query,'scope':scope,'conversation':list(dialogue)[-30:],'displayed':list(displayed)[-24:],'discovery':discovery},
  {'reference':{'type':'choice','instructions':
   'Select the most useful actual reference for this request. For work scope prefer an entire work, not a component. '
   'Tutorials, reviews, news and production breakdowns are valid creative references when the user wants that format. '
   'They may also teach a method. Match the requested use, not just subject words. '
   'During overall discovery, retrieve analogous complete works whose storytelling or visual treatment helps choose a direction. '
   'The reference need not share the exact subject, location or product. Do not start with isolated room or caption examples unless requested. '
   'Match the requested format and viewing experience before subject similarity: a narrative film needs cinematic story references, '
   'not a creator challenge or engineering tutorial merely because both involve building something. '
   'Likewise an advertisement, vlog or lesson needs references for that format rather than unrelated works sharing its topic. '
   'Resolve references such as the first or that quieter one against displayed items and conversation. '
   'Retain liked properties and reject properties the user wants to change; do not re-offer an unchanged rejected look as an improvement. '
   'When discovery is provided, retrieve evidence for its next unresolved axis, rather than copies of the closest match. '
   'Different values of the unresolved axis are useful alternatives; preserve other settled preferences. '
   'A changed direction supersedes conflicting old preferences and rejected traits; a hypothetical does not. '
   'Work metadata comes from title/publisher/description, so do not imagine camera, color or audio details. '
   'Detailed video observations are available only where explicitly included. Return none when required evidence is missing.',
   'criteria':{**choices,'none':'No supported match'}}},timeout=timeout)
 batches=[]
 remaining=criteria
 semaphore=asyncio.Semaphore(4)
 async def bounded_judge(group):
  async with semaphore:return await judge_choices(group)
 failed=None
 # Every candidate enters round one. Bound fan-out and reduce repeatedly so
 # growing the library never overflows the final 255-choice request.
 while len(remaining)>254 or len(choice_batches(remaining))>1:
  groups=choice_batches(remaining)
  round_results=await asyncio.gather(*(bounded_judge(group) for group in groups))
  batches.extend(round_results)
  failed=next((b for b in round_results if not b.get('available')),None)
  if failed:break
  finalists={}
  for group,batch in zip(groups,round_results):
   probabilities=batch.get('answers',{}).get('reference',{}).get('probabilities',{})
   # Small dense batches must also shrink; otherwise reduction can loop forever.
   keep=min(5,max(1,len(group)//2))
   for key in sorted(group,key=lambda k:-probabilities.get(k,0))[:keep]:
    if probabilities.get(key,0)>0:finalists[key]=group[key]
  if len(finalists)>=len(remaining):
   failed={'available':False,'reason':'candidate_evidence_exceeds_batch_budget'}
   break
  remaining=finalists
 result=failed or (await judge_choices(remaining) if remaining else
                  {'available':True,'answers':{'reference':{'probabilities':{'none':1}}}})
 answer=result.get('answers',{}).get('reference',{});prob=answer.get('probabilities',{})
 ranked=sorted(rows,key=lambda r:-prob.get(r['id'],0))
 verification=None;unavailable=set();verification_ms=0
 if verify_matches and result.get('available'):
  finalists=[r for r in ranked if prob.get(r['id'],0)>0][:12]
  if finalists:
   verification_started=time.perf_counter()
   verification_request=editor_jev.judge(user_id,
    {'request':query,'conversation':list(dialogue)[-30:],'discovery':discovery,
     'candidates':{r['id']:r['search_text'] for r in finalists}},
    {r['id']:{'type':'choice','instructions':
      'Evaluate ONLY candidates['+r['id']+']. Check it against explicit current requirements, independently of its relative rank. '
      'Reject contradicted medium/format: live-action behind-the-scenes is not a 2D anime reference, '
      'a filmmaking tutorial is not a narrative film, a travel ad is not an architect presenting a home. '
      'Allow analogous subjects if format and desired experience fit. Latest genuine pivot overrides old constraints. '
      'Use uncertain when metadata cannot establish fit; never invent visual evidence.',
     'criteria':{'supported':'Supported relevant reference','contradicted':'Conflicts with explicit current requirements','uncertain':'Insufficient evidence'}} for r in finalists},timeout=timeout)
   # Content fit and URL availability read the same shortlist independently.
   # Keep both checks, but do not make the user wait for them sequentially.
   if embedded:
    verification,unavailable=await asyncio.gather(verification_request,unavailable_reference_ids(finalists))
   else:verification=await verification_request
   verification_ms=round((time.perf_counter()-verification_started)*1000)
   if verification.get('available'):
    rejected={ident for ident,a in verification.get('answers',{}).items()
              if a.get('probabilities',{}).get('contradicted',0)>=.5}
    ranked=[r for r in ranked if r['id'] not in rejected]
    verification['rejected_ids']=sorted(rejected)
 ranked=[r for r in ranked if r['id'] not in unavailable]
 top=prob.get(ranked[0]['id'],0) if ranked else 0
 selected=[] if not top or prob.get('none',0)>=top else [r for r in ranked if prob.get(r['id'],0)>=max(.001,top*.1)][:limit]
 if route['mode']=='genres' and (not result.get('available') or not selected):
  fallback=await search(user_id,query,scope=scope,limit=limit,timeout=timeout,dialogue=dialogue,
                        embedded=embedded,displayed=displayed,discovery=discovery,routing='full',verify_matches=verify_matches)
  fallback['routing']={**route,'fallback':'no_supported_result','first_candidate_count':len(rows)}
  fallback['elapsed_ms']=round((time.perf_counter()-started)*1000)
  return fallback
 return {'available':result.get('available',False),'elapsed_ms':round((time.perf_counter()-started)*1000),
  'routing':route,'verification':verification,'verification_wall_ms':verification_ms,'unavailable_ids':sorted(unavailable),'total_candidate_count':total_count,
  'candidate_count':len(rows),'request_characters':len(json.dumps(criteria,ensure_ascii=False)),
  'batch_count':len(batches),'batch_elapsed_ms':[b.get('elapsed_ms') for b in batches],
  'batch_usage':[b.get('usage') for b in batches],
  'results':[{k:r.get(k) for k in ('id','title','url','label_basis','start','end')}|{'ranking_probability':prob.get(r['id'],0)} for r in selected],
  'shortlist':[{k:r.get(k) for k in ('id','title','url','search_text')} for r in ranked if prob.get(r['id'],0)>0][:12] if discovery else [],
  'none_probability':prob.get('none'),'usage':result.get('usage'),'failure':None if result.get('available') else {k:result.get(k) for k in ('reason','error_type','http_status')}}
