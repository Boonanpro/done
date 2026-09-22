"""Local, inspected reference previews. No network discovery or generation."""
import asyncio
import copy
import json
import math
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'docs/reference-library.json'
COMPONENTS = ROOT / 'docs/component-library.json'
MEDIA = ROOT / 'uploads/reference-library'


def selection_description(row):
    """Expose evidence and applicability, not just a visual keyword label.

    Inspection proves the preview plays, not professional production quality.
    Keep these details in model context rather than captions below the preview.
    """
    parts = [row.get('description', '')]
    if row.get('reference_role'):
        parts.append('Demonstrates: ' + row['reference_role'])
    if row.get('use_cases'):
        parts.append('Useful for: ' + '; '.join(row['use_cases']))
    if row.get('limitations'):
        parts.append('Limits: ' + '; '.join(row['limitations']))
    if row.get('component') and row.get('evidence_role') != 'finished_study':
        parts.append('Mechanism demonstration with editable source; not a finished film or proof of final production quality.')
    if row.get('evidence_role') == 'finished_study':
        parts.append('Rendered visual study with editable source. ' + row.get('quality_evidence',''))
    if row.get('reproduction_status') == 'reference_only':
        parts.append('Existing reference footage; not newly generated for this user.')
    return ' '.join(parts)


async def astra_select(state, *, effort='medium'):
    """Small read-only selection turn; never changes the production model effort."""
    import os
    import re
    from app.services.editor_codex import CodexTurn
    owner=CodexTurn()
    config_path=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'config.toml'
    names=re.findall(r'^\[mcp_servers\.([^\].]+)\]',config_path.read_text(encoding='utf-8'),re.M) if config_path.exists() else []
    started=time.perf_counter()
    try:
        await asyncio.wait_for(owner.start([{'role':'user','content':json.dumps(state,ensure_ascii=False)}],[],
            'Select existing visual references from candidates for the current request, retaining conversation preferences. '
            'Different subject is not different drawing style. Do not invent visual evidence. '
            'Choose up to 3 IDs; fewer is fine when the library lacks suitable options. '
            'Requests to see, compare, or refine references can reuse previously shown examples. Decide from the original conversation, not only the last sentence. '
            'Return handled=false for modifying/creating/deleting content, explicit Web search, playback controls or unrelated questions. '
            'Return only JSON {"handled":boolean,"ids":[...],"insufficient":boolean}. No tools, research or explanation.',
            'gpt-6-astra',config_overrides={'features.shell_tool':False,'features.fast_mode':True,
                'service_tier':'fast','model_reasoning_effort':effort,
                'project_doc_max_bytes':0,'skills.max_context_tokens':1,
                'mcp_servers':{n.strip('"'):{'enabled':False} for n in names}}),timeout=20)
        startup_ms=round((time.perf_counter()-started)*1000)
        output=''
        async def read():
            nonlocal output
            while True:
                e=await owner.receive();method=e.get('method');p=e.get('params',{})
                if method=='item/agentMessage/delta':output+=p['delta']
                elif method=='turn/completed':
                    if p['turn']['status']!='completed':raise RuntimeError('Selection failed')
                    return
                elif method=='process/closed':raise RuntimeError('Selection connection closed')
                elif 'id' in e and method:owner.send({'id':e['id'],'error':{'code':-32601,'message':'No tools for reference selection'}})
        await asyncio.wait_for(read(),timeout=max(.1,20-(time.perf_counter()-started)))
        if output.startswith('```'):output=output.split('```')[1].removeprefix('json').strip()
        result=json.loads(output)
        if not isinstance(result,dict):
            raise ValueError('Invalid selection response')
        ids=result.get('ids',[]);known={i['id'] for i in state['candidates']}
        if not isinstance(ids,list) or len(ids)>3 or any(not isinstance(i,str) or i not in known for i in ids) or len(set(ids))!=len(ids):
            raise ValueError('Invalid selection')
        return {'handled':result.get('handled') is True,'ids':ids,'insufficient':result.get('insufficient') is True,'startup_ms':startup_ms,'total_ms':round((time.perf_counter()-started)*1000)}
    finally:
        owner.close()


def catalog():
    if not CATALOG.exists():
        return []
    rows = json.loads(CATALOG.read_text(encoding='utf-8'))
    if COMPONENTS.exists():
        rows += [{**r,'category':r['family'],'family':r['id']} for r in json.loads(COMPONENTS.read_text(encoding='utf-8'))]
    return [r for r in rows if r.get('inspection')!='pending' and (r.get('kind') in ('composition','scene') or (MEDIA / (r['id'] + r.get('extension','.jpg'))).is_file())]

def selectable(row):
    # Keep old projects and media URLs readable, but do not propose held previews.
    return row.get('quality_status') not in ('quarantined', 'rejected', 'needs_design_work')


def media_path(ident):
    row=next((r for r in catalog() if r['id']==ident and r.get('kind') not in ('composition','scene')),None)
    if not row:
        raise ValueError('Unknown reference')
    extension=row.get('extension','.jpg')
    if extension not in ('.jpg','.png','.mp4','.webm'):
        raise ValueError('Unsupported reference file')
    return MEDIA / (ident + extension)


def proposal(row):
    kind=row.get('kind','image')
    # Keep verified appearance available to the conversational model. This is
    # model context, not a paragraph rendered under the user's visual.
    item={'kind':kind,'title':row['title'],'library_id':row['id'],'note':selection_description(row)}
    if row['id'].startswith('yt-'):
        item['url']=row['url']
    elif kind in ('composition','scene'):
        item[kind]=copy.deepcopy(row[kind])
    else:
        item['url']='/api/v1/editor-assistant/reference-library/media/'+row['id']
    if row.get('source_url') or row.get('url'):
        item['source_url']=row.get('source_url') or row['url']
    return item


def rank(answers, rows, diverse, count=2):
    candidates=[]
    for row in rows:
        score=answers.get(row['id'],{}).get('score')
        # Reference comparisons can be useful before the user can describe a
        # final match. 1.5 is a tested ranking cutoff, not a probability claim.
        if isinstance(score,(int,float)) and math.isfinite(score) and 1.5<=score<=3:
            candidates.append((score,row))
    candidates.sort(key=lambda x:(-x[0],x[1]['id']))
    # Do not pad a strong match with substantially weaker suggestions merely
    # to fill two slots. Scores are ranking evidence, not user probabilities.
    if candidates and candidates[0][0]>=2.65:
        candidates=[c for c in candidates if c[0]>=candidates[0][0]-.3]
    selected=[];families=set()
    for _,row in candidates:
        if diverse and row['family'] in families:
            continue
        selected.append(row);families.add(row['family'])
        if len(selected)==count:
            break
    return selected


async def suggest(user, room, content, request, dialogue, current=lambda:True, *, selection_only=False, presentations=None, allow_astra_fallback=True):
    from app.services.editor_jev import judge
    from app.services.editor_presentation import present
    if not isinstance(request,str) or not request.strip() or len(request)>2000:
        raise ValueError('request must contain 1..2000 characters')
    start=time.perf_counter();rows=[r for r in catalog() if selectable(r)]
    candidates=[{**{k:r[k] for k in ('id','title','description','family')},'kind':r.get('kind','image')} for r in rows]
    state={'candidates':candidates,'conversation':dialogue[-30:],'recent_presentations':presentations or [],'request':request}
    intent_question={'type':'choice','instructions':'Classify the latest request in conversation. Do not decide feasibility. Refining which example to see is still examples. A prohibition on search/generation is not a request for it.',
        'criteria':{'examples':'See or compare existing reference examples','other':'Create/edit/delete, explicit Web search, playback control or unrelated'}}
    questions={r['id']:{'type':'score','instructions':
        f'Assess only reference ID {r["id"]}: {r["description"]} Medium: {r.get("kind","image")}. Does this actual reference fit the latest request AND retained preferences from conversation? Explicit rejected characteristics and wrong media mean 0. Do not score another candidate or an imagined adaptation.',
        'criteria':['Contradicts the request or wrong medium','Weak or insufficient evidence','Relevant but with limitations','Strong direct match']} for r in rows}
    questions['same_style']={'type':'noul','instructions':'Does the user explicitly want variants within the SAME style/design (different people, timing, speed, or one detail)? No if they want distinct styles or have not chosen a style yet.'}
    questions['reference_request']=intent_question
    result=await judge(user,state,questions,timeout=3.5)
    answers=result.get('answers',{})
    intent=answers.get('reference_request',{})
    reference_confidence=intent.get('confidence',0) if intent.get('choice')=='examples' else 0
    # Before a direction is chosen, offer distinct families instead of making
    # the user specify a comparison mode or waiting for a second model.
    same_style=answers.get('same_style',{}).get('noul',0)
    selected=rank(answers,rows,same_style<.8)
    response={'ok':True,'library_only':True,'ranking_ms':round((time.perf_counter()-start)*1000),'ranked_count':len(rows),
              'candidates':candidates,
              'scores':answers,'presented':False,'reference_confidence':reference_confidence,'ranking_available':result.get('available',True),'ranking_failure':result.get('reason')}
    if selection_only:
        response['handled']=bool(selected) and reference_confidence>=.9
        response['selected_library_ids']=[r['id'] for r in selected] if response['handled'] else []
        response['selection_backend']='jev'
        if allow_astra_fallback and not response['handled'] and (reference_confidence>=.6 or result.get('available') is False):
            try:
                fallback=await astra_select(state)
                response.update(handled=fallback['handled'],selected_library_ids=fallback['ids'],insufficient=fallback['insufficient'],selection_backend='astra_cli',selection_timing={k:fallback.get(k) for k in ('startup_ms','total_ms')})
            except (ValueError,RuntimeError,asyncio.TimeoutError):
                response['needs_judgment']=True
        return response
    if not current():
        return {'ok':False,'canceled':True}
    if selected:
        response.update(await asyncio.to_thread(present,room,content,[proposal(r) for r in selected]))
        response['presented']=True
        response['selected_library_ids']=[r['id'] for r in selected]
    else:
        response['needs_judgment']=True
        response['note']='確信不足または候補不足。会話原文と確認済み記述で判断し、適切ならpresent_reference_examplesで提示。適切な候補がなければ不足と伝える。この経路はWeb検索や生成を自動実行しない。'
    response['elapsed_ms']=round((time.perf_counter()-start)*1000)
    return response


def show(room,content,ids,comparison_key=None):
    from app.services.editor_presentation import present
    if not isinstance(ids,list) or not 1<=len(ids)<=3 or len(set(ids))!=len(ids):
        raise ValueError('Choose 1..3 distinct reference IDs')
    rows={r['id']:r for r in catalog()}
    if any(i.startswith('yt-') for i in ids):
        from app.services.reference_url_index import presentation_rows
        rows.update({r['id']:r for r in presentation_rows()})
    if any(i not in rows for i in ids):
        raise ValueError('Unknown reference')
    return present(room,content,[proposal(rows[i]) for i in ids],comparison_key=comparison_key)
