"""Persist agreed direction and deliver revisions to an already running worker."""
import copy
import json
import time
from app.services import timeline_draft as td


def notify_worker(room, content_id, changes):
    from app.services.timeline_agent import content_busy
    from app.services.editor_job_updates import submit
    job_id = content_busy(content_id)
    if not job_id:
        return None
    update = submit(room, job_id, '作品の合意内容が更新されました。今回変わった条件を既存の制作へ反映し、変更されていない条件は保持してください。\n' + json.dumps(changes, ensure_ascii=False))
    return {'job_id':job_id, 'update_id':update['id'], 'state':'instruction_pending'}


def save_brief(room, content_id, changes):
    permitted = {k:str(v)[:8000] for k,v in changes.items()
                 if k in {'intent','taste','references','constraints','proposals'}}
    with td.ContentsLock(room):
        rows = td._read_contents_raw(room)
        content = td._find_content(rows, content_id)
        if content is None:
            raise ValueError('作品が見つかりません')
        brief = content.setdefault('creative_brief', {})
        changed = {k:v for k,v in permitted.items() if brief.get(k) != v}
        if not changed:
            return {'ok':True,'saved':permitted,'changed':False}
        history = content.setdefault('creative_brief_history', [])
        history.append({'at':time.time(),'before':copy.deepcopy(brief),'changes':changed})
        brief.update(changed)
        td._write_contents_raw(room, rows)
    return {'ok':True,'saved':permitted,'changed':True,'delivery':notify_worker(room, content_id, changed)}
