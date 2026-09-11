"""Actual tool lifecycles for production cards and timeline highlights."""
import json,time,uuid
from app.services import timeline_draft as td

def start(room,job,tool,args):
    if not job:return None
    category=('generation' if tool.startswith('generate_') else 'review' if tool in {'watch_render','watch_video','validate_draft','render_frame'} else 'editing' if tool in {'add_clip','add_audio','append_clip','remove_clip','trim_clip','set_clip_props','move_clip','auto_captions','add_overlay'} else 'inspect')
    if tool in {'prepare_motion_project', 'render_motion_project','apply_edits','set_clip','animate_clip','Write','Edit'}:
        category = 'editing'
    row={'id':uuid.uuid4().hex,'tool':tool,'category':category,'state':'running','started_at':time.time(),
         'model':args.get('model') or ('Qwen3-TTS' if tool=='generate_speech' else 'gemini-omni-1.1-flash' if tool=='generate_video' and args.get('provider','google')=='google' else None),
         'provider':args.get('provider','google') if tool=='generate_video' else None,
         'clip_ids':[args['clip_id']] if args.get('clip_id') else args.get('clip_ids',[])}
    folder=td._room_dir(room)/'jobs'/job/'activity';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(row['id']+'.json');write(path,row)
    return path,row

def write(path,row):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(row,ensure_ascii=False),encoding='utf-8');tmp.replace(path)

def finish(operation,failed=False,error=''):
    if operation:
        path,row=operation;row.update(state='failed' if failed else 'done',ended_at=time.time(),error=str(error)[:600]);write(path,row)

def read(room,job,status):
    rows=[]
    for path in (td._room_dir(room)/'jobs'/job/'activity').glob('*.json'):
        try:row=json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,OSError):continue
        if status not in {'running','queued'} and row['state']=='running':row['state']='interrupted'
        rows.append(row)
    return sorted(rows,key=lambda r:r['started_at'],reverse=True)[:12]
