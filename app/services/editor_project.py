"""On-demand project knowledge shared by conversation and production.

Read bounded, current evidence instead of putting the whole project in a prompt.
"""
import json
from pathlib import Path
from app.services import timeline_draft as td, timeline_live as tl, timeline_context as tcx


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return default


def conversation(room,content_id,limit=30):
    rows=[]
    for path in (td._room_dir(room)/'assistant').glob('*.json'):
        turn=read_json(path,{})
        ctx=turn.get('context',{})
        if ctx.get('content_id')==content_id and ctx.get('utterance'):
            rows.append({'at':turn.get('created_at',0),'text':ctx['utterance'],'playhead':ctx.get('playhead')})
    return sorted(rows,key=lambda r:r['at'])[-max(1,min(int(limit),60)):]


def dialogue(room, content_id, limit=30, before=None):
    """Read both sides on demand; assistant suggestions are never user decisions."""
    from datetime import datetime
    def timestamp(value):
        try:
            return float(value)
        except (ValueError, TypeError):
            try:return datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
            except ValueError:return 0.
    folder=td._room_dir(room)/'assistant'
    turns={p.stem:read_json(p,{}) for p in folder.glob('*.json')}
    rows=[]; spoken=set(); assistant_turns=set()
    for path in (folder/'events').glob('*.jsonl'):
        with path.open(encoding='utf-8') as f:
            for line in f:
                try:e=json.loads(line)
                except ValueError:continue
                if e.get('type') not in {'user_transcript','assistant_transcript'} or not e.get('text'):continue
                ctx=turns.get(e.get('turn_id'),{}).get('context',{})
                if (e.get('content_id') or ctx.get('content_id'))!=content_id:continue
                role='user' if e['type']=='user_transcript' else 'assistant'
                rows.append({'at':timestamp(e.get('at')),'role':role,'text':e['text'],
                             'turn_id':e.get('turn_id'),'playhead':ctx.get('playhead')})
                if role=='user':spoken.add(e.get('turn_id'))
                else:assistant_turns.add(e.get('turn_id'))
    for tid,turn in turns.items():
        ctx=turn.get('context',{})
        if ctx.get('content_id')==content_id and ctx.get('utterance') and tid not in spoken:
            rows.append({'at':timestamp(turn.get('created_at')),'role':'user','text':ctx['utterance'],
                         'turn_id':tid,'playhead':ctx.get('playhead')})
        if ctx.get('content_id')==content_id and tid not in assistant_turns:
            reply=turn.get('reasoning',{}).get('reply_text')
            if reply:
                rows.append({'at':turn['reasoning'].get('reply_at',timestamp(turn.get('created_at'))+.001),
                    'role':'assistant','text':reply,'turn_id':tid,'playhead':ctx.get('playhead')})
    rows.sort(key=lambda r:r['at'])
    if before is not None:rows=[r for r in rows if r['at']<float(before)]
    size=max(1,min(int(limit),60)); page=rows[-size:]
    return {'messages':page,'before':page[0]['at'] if len(rows)>size else None}


def status(room, content_id):
    from app.services import editor_activity,editor_job_updates,editor_questions
    content, seq = tl.live_sequence(room, content_id)
    jobs = []
    for j in read_json(td._room_dir(room)/'jobs.json', []):
        if j.get('content_id') != content_id:
            continue
        events = []
        path = td._room_dir(room)/'jobs'/j['id']/'events.jsonl'
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        events.append(event)
                except ValueError:
                    # The worker may still be appending the last event.
                    continue
        model = next((e.get('model') for e in events if e.get('model')), None)
        jobs.append({k:j.get(k) for k in ('id','status','created_at','updated_at','error','draft_id','execution')} | {
            'request':str(j.get('instruction',{}).get('revision_text',''))[:1600],
            'editing_model':model,'generation_models':list(dict.fromkeys(e['model'] for e in events if e.get('type')=='generation' and e.get('model'))),
            'events':[{k:(str(e.get(k))[:2000] if k=='text' else e.get(k)) for k in ('created_at','type','text')} for e in [e for e in events if e.get('text')][-4:]],
            'activity':editor_activity.read(room,j['id'],j['status']),
            'pending_instructions':len(editor_job_updates.pending(room,j['id'])),
            'question':editor_questions.read(room,j['id']) if j['status'] not in {'canceled','failed'} else None,
            'selected_clips':j.get('instruction',{}).get('selected_clips',[]),
            'result':j.get('result',{})})
    jobs.sort(key=lambda j:j.get('created_at') or '', reverse=True)
    work=[dict(w) for w in (content or {}).get('editor_work',[])]
    for w in work:
        j=next((j for j in jobs if j['id']==w.get('job_id')),None)
        if j and w.get('status')=='running' and j['status'] in {'done','failed','canceled'}:
            w['status']={'done':'needs_review','failed':'blocked','canceled':'canceled'}[j['status']]
    return {'ok':True,'content_id':content_id,'format':(seq or {}).get('format'),
            'clip_count':sum(len(t.get('clips',[])) for t in (seq or {}).get('tracks',[])),
            'brief':(content or {}).get('creative_brief',{}), 'work':work,
            'presentation':(content or {}).get('presentation'),
            'jobs':[j for j in jobs if j['status'] in {'running','queued'}]+[j for j in jobs if j['status'] not in {'running','queued'}][:8]}


def current_status(room, content_id):
    """Conversation reads current facts; historical error text is not live state."""
    s=status(room,content_id)
    active=[j for j in s['jobs'] if j['status'] in {'queued','running'}]
    latest=next((j for j in s['jobs'] if j['status'] not in {'queued','running'}),None)
    return {'ok':True,'active_count':len(active),'active_jobs':active,
            'editing_model':'gpt-6-astra',
            'latest_finished_job':({k:latest.get(k) for k in ('id','status','updated_at')} |
                {'committed':latest.get('result',{}).get('committed'),
                 'draft_id':latest.get('draft_id') or latest.get('result',{}).get('draft_id'),
                 'outcome':latest.get('result',{}).get('outcome'),
                 'summary':latest.get('result',{}).get('summary'),
                 'error_at_that_time':latest.get('error')}) if latest else None}


def stop_production(room, content_id, job_id=None):
    from app.api.production_asset_routes import cancel_production_job
    rows=read_json(td._room_dir(room)/'jobs.json', [])
    matching=[j for j in rows if j.get('content_id')==content_id and (not job_id or j['id']==job_id)]
    if job_id and not matching:
        return {'ok':False,'error':'この作品の仕事ではありません'}
    stopped=[]
    for job in matching:
        if job.get('status') in {'running','queued'}:
            stopped.append({'job_id':job['id'], **cancel_production_job(job['id'],room)})
    return {'ok':all(j.get('ok') for j in stopped),'jobs':stopped,
            'note':'停止処理の結果です。既に保存された編集は取り消していません。' if stopped else '進行中の制作はありません。'}


def inspect_range(room, content_id, start, end):
    _, seq = tl.live_sequence(room, content_id)
    start,end = float(start),float(end)
    if not 0 <= start < end <= float(seq.get('duration',0))+.01:
        raise ValueError('作品内の開始・終了時刻を指定してください')
    assets=tl._assets(room)
    analyses={aid:a.get('metadata',{}).get('audio_analysis') for aid,a in assets.items() if a.get('metadata',{}).get('audio_analysis')}
    rows=tcx.timeline_transcript(seq,analyses,start,end)
    clips=[dict(c,lane=n,lane_type=t.get('type')) for n,t in enumerate(seq.get('tracks',[])) for c in t.get('clips',[]) if c['timeline_start']<end and c['timeline_end']>start]
    ids={c.get('asset_id') for c in clips}
    return {'ok':True,'start':start,'end':end,'clips':clips[:100], 'has_more':len(clips)>100,
            'speech':rows,'speech_available':bool(rows),'note':'speechは元素材の解析です。字幕を発話の証拠として扱わないでください。画像の雰囲気はasset_imageやtimeline_frameで実物を見て判断してください。',
            'assets':[{'id':aid,'name':a.get('filename'), 'metadata':{k:v for k,v in a.get('metadata',{}).items() if k in {'width','height','duration','model','prompt','reference_asset_ids'}}} for aid,a in assets.items() if aid in ids]}


def history(room, content_id, offset=0):
    rows=[]
    for path in (td._room_dir(room)/'drafts').glob('*.json'):
        d=read_json(path,{})
        if d.get('content_id')!=content_id or not d.get('committed_at'):continue
        rows.append(d)
    rows.sort(key=lambda d:d['committed_at'],reverse=True)
    offset=max(0,int(offset));page=rows[offset:offset+5]
    return {'ok':True,'edits':[{'draft_id':d['draft_id'],'at':d['committed_at'],'job_id':d.get('job_id'),
                              'changes':tl.describe_changes(d['base_sequence'],d['sequence'])} for d in page],
            'next_offset':offset+5 if len(rows)>offset+5 else None}


def asset_image(room, asset_id):
    import base64
    from io import BytesIO
    from PIL import Image
    asset=tl._assets(room).get(asset_id)
    if not asset:
        raise ValueError('素材が見つかりません')
    path=Path(asset.get('local_path') or '')
    if path.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'} or not path.is_file():
        raise ValueError('静止画素材を指定してください。映像はtimeline_frameで確認できます。')
    with Image.open(path) as im:
        im=im.convert('RGB');im.thumbnail((1280,1280))
        buf=BytesIO();im.save(buf,format='JPEG',quality=90)
    return {'ok':True,'asset_id':asset_id,'metadata':asset.get('metadata',{}),
            'image':'data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode()}


def update_work(room, content_id, work_id, title, state, note='', job_id=None):
    if state not in {'pending','running','needs_review','done','blocked','canceled'}:
        raise ValueError('作業状態が不正です')
    with td.ContentsLock(room):
        contents=td._read_contents_raw(room);c=td._find_content(contents,content_id)
        if c is None:raise ValueError('作品が見つかりません')
        work=c.setdefault('editor_work',[])
        item=next((w for w in work if w['id']==work_id),None)
        if item is None:
            item={'id':work_id};work.append(item)
        item.update(title=str(title)[:400],status=state,note=str(note)[:2000])
        if job_id:item['job_id']=job_id
        td._write_contents_raw(room,contents)
    return {'ok':True,'work':work}
