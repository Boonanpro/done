"""Render editable lettering from a trusted, room-local After Effects template."""
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.services import envato_shelf as shelf, timeline_draft as td, editor_workflows
from app.services.editor_media import import_media

REGISTRY = Path.home() / '.dan/workspace/ae-typography'


def render(template, values, dest):
    with shelf._slot(), tempfile.TemporaryDirectory(prefix='render-', dir=shelf.SHELF) as scratch:
        root = Path(scratch)
        event = root / 'event'
        subprocess.run(['swiftc', shelf.SCRIPTS / 'event.swift', '-o', event], check=True, capture_output=True, timeout=90)
        app = shelf.AE / 'Adobe After Effects 2027.app/Contents/MacOS/After Effects'
        worker = subprocess.Popen([app,'-m','-noui','-ApplePersistenceIgnoreState','YES','-NSQuitAlwaysKeepsWindows','NO'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=shelf._low)
        def send(script, timeout=120):
            return subprocess.run([event,str(worker.pid),script],capture_output=True,timeout=timeout)
        try:
            ready=root/'ready'
            deadline=time.monotonic()+90
            while time.monotonic()<deadline and worker.poll() is None:
                send('var f=new File('+json.dumps(str(ready))+'); f.open("w");f.write(app.version);f.close();',30)
                if ready.exists():break
                time.sleep(.5)
            if not ready.exists():raise RuntimeError('After Effects を起動できません')
            job={**template,'values':values,'output':str(dest),'workingProject':str(root/'result.aep'),'report':str(root/'status')}
            script=root/'edit.jsx'
            script.write_text('var DAN_TEXT_JOB='+json.dumps(job)+';\n'+Path(__file__).with_name('change.jsx').read_text())
            send('$.evalFile(new File('+json.dumps(str(script))+'))',300)
            status=root/'status'
            if not status.exists() or status.read_text()!='ok':
                raise RuntimeError(status.read_text() if status.exists() else '元の文字を読み込めません')
        finally:
            if worker.poll() is None:
                try:
                    send('app.beginSuppressDialogs();app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);app.quit();',8)
                    worker.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    worker.terminate()
                    try: worker.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        worker.kill();worker.wait()
        if not template['still']:shelf._aerender(root/'result.aep',timeout=1800)
        if not dest.is_file() or dest.stat().st_size<256:raise RuntimeError('文字を描画できませんでした')


def update(request):
    room=str(uuid.UUID(request['room'])); content=str(uuid.UUID(request['content']))
    def selected(seq):
        clip=next((c for t in seq['tracks'] for c in t['clips'] if c['id']==request['clip']),None)
        if not clip or clip.get('asset_id')!=request['asset'] or not clip.get('ae_text'):
            raise ValueError('このクリップが変わりました。選び直してください')
        return clip
    live=td._find_content(td._read_contents_raw(room),content)
    clip=selected(live['timeline']['sequence'])
    spec=clip['ae_text']; cfg=json.loads((REGISTRY/(room+'.json')).read_text())[spec['template']]
    values=request['values']
    if len(values)!=len(cfg['fields']) or not all(isinstance(v,str) and v.strip() and len(v)<=300 for v in values):
        raise ValueError('各欄に300文字以内で入力してください')
    if values==spec['values']:return {'asset':clip['asset_id']}
    with tempfile.TemporaryDirectory() as tmp:
        dest=Path(tmp)/('text.png' if cfg['still'] else 'text.mov')
        render(cfg,values,dest)
        media=import_media(room,dest,values[0]+'（編集できる文字）',origin='editor',preserve_canvas=True)
        if not media.get('ok'):raise RuntimeError('文字の素材を保存できません')
    with td.content_edit_lock(room,content) as locked:
        if not locked:raise RuntimeError('編集中のため反映できません。もう一度お試しください')
        draft=td.create_draft(room,content)
        clip=selected(draft['sequence'])
        clip.update(asset_id=media['asset_id'],ae_text={**spec,'values':values},label=values[0])
        result=editor_workflows.commit(draft,set(draft.get('baseline_problems') or []))
        if not result.get('ok'):raise ValueError('別の編集がありました。クリップを選び直してください')
    return {'asset':media['asset_id']}


if __name__=='__main__':
    directory=Path(sys.argv[1])
    try:
        result={'ok':True,**update(json.loads((directory/'request.json').read_text()))}
    except Exception as exc:
        result={'ok':False,'error':str(exc)[:350]}
    tmp=directory/'result.tmp'
    tmp.write_text(json.dumps(result,ensure_ascii=False));os.replace(tmp,directory/'result.json')
