"""Render a selected local Envato composition in an isolated After Effects instance."""
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

SHELF = Path.home() / '.dan/workspace/envato-shelf'
SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts/envato_shelf'
AE = Path('/Applications/Adobe After Effects 2027')


def catalog():
    return json.loads((SHELF / 'catalog.json').read_text())


def describe(item):
    return {**{k: item[k] for k in ('id', 'group', 'name', 'duration', 'url', 'sourceName')},
            'fields': [{k: f[k] for k in ('label', 'type', 'example')} for f in item['fields']]}


def resolve_values(item, supplied, assets):
    expected = {field['label'] for field in item['fields']}
    if set(supplied) != expected:
        raise ValueError('差し替え欄: ' + '、'.join(sorted(expected)))
    values = []
    for field in item['fields']:
        value = supplied[field['label']]
        kind = field['type']
        if kind in ('photo', 'photos'):
            ids = [value] if kind == 'photo' else value
            if not isinstance(ids, list) or not ids:
                raise ValueError('作品の写真素材を指定してください')
            paths = []
            for ident in ids:
                asset = assets.get(ident, {})
                path = Path(asset.get('local_path') or asset.get('original_uri') or '')
                if asset.get('kind') != 'image' or not path.is_file():
                    raise ValueError('作品にある写真素材を指定してください')
                paths.append(str(path.resolve()))
            value = paths[0] if kind == 'photo' else paths
        elif kind == 'number':
            value = float(value)
            if not math.isfinite(value):
                raise ValueError('有限の数を指定してください')
        elif not isinstance(value, str) or not value.strip():
            raise ValueError(field['label'] + 'を入力してください')
        values.append(value)
    return values


def render(item, values, folder, *, font='SourceHanSansJP-Bold'):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    # Include photo content so edits to existing photos cannot return a stale render.
    key = hashlib.sha256(json.dumps([item, values, font], sort_keys=True).encode())
    key.update((SCRIPTS / 'prepare.jsx').read_bytes())
    for field, value in zip(item['fields'], values):
        if field['type'] in ('photo', 'photos'):
            for path in ([value] if field['type'] == 'photo' else value):
                key.update(Path(path).read_bytes())
    output = folder / (key.hexdigest() + '.mov')
    if output.is_file():
        return output
    with tempfile.TemporaryDirectory(dir=folder) as scratch:
        root = Path(scratch)
        app = AE / 'Adobe After Effects 2027.app/Contents/MacOS/After Effects'
        binary = root / 'event'
        subprocess.run(['swiftc', SCRIPTS / 'event.swift', '-o', binary], check=True, capture_output=True, timeout=90)
        worker = subprocess.Popen([app, '-m', '-noui'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            def event(code):
                if worker.poll() is not None:
                    raise RuntimeError('After Effects が終了しました')
                return subprocess.run([binary, str(worker.pid), code], timeout=190,
                                      capture_output=True, text=True)
            ready = root / 'ready'
            deadline = time.monotonic() + 70
            while time.monotonic() < deadline:
                event('var f=new File('+json.dumps(str(ready))+'); f.open("w"); f.write(app.version); f.close();')
                if ready.exists():
                    break
                time.sleep(1)
            else:
                raise RuntimeError('書き出し用の After Effects を起動できません')
            event('app.beginSuppressDialogs(); app.open(new File('+json.dumps(item['source'])+'));')
            job = dict(item=item, values=values, font=font, width=1920, fps=30, mode='render',
                       report=str(root/'status'), output=str(root/'render.mov'), project=str(root/'render.aep'),
                       repair=item['id'].split('-')[0] in {'lower','glitch','transition','carousel'})
            script = root / 'job.jsx'
            script.write_text('var DAN_SHELF_JOB='+json.dumps(job)+';\n'+(SCRIPTS/'prepare.jsx').read_text())
            event('$.evalFile('+json.dumps(str(script))+')')
            report = root/'status'
            if not report.exists() or report.read_text() != 'ok':
                raise RuntimeError(report.read_text() if report.exists() else 'テンプレートを準備できません')
        finally:
            if worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait()
        subprocess.run([AE/'aerender', '-project', root/'render.aep', '-rqindex', '1'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=1800)
        path = root/'render.mov'
        check = subprocess.check_output([shutil.which('ffprobe') or '/opt/homebrew/bin/ffprobe', '-v', 'error',
            '-select_streams','v:0','-show_entries','stream=pix_fmt,duration,width','-of','json',path],text=True)
        stream = json.loads(check)['streams'][0]
        if 'a' not in stream['pix_fmt'] or abs(float(stream['duration']) - item['duration']) > .08:
            raise RuntimeError('透明度または書き出した尺が指定と一致しません')
        os.replace(path, output)
    return output
