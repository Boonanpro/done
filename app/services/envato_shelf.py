"""Render a selected local Envato composition in an isolated After Effects instance."""
import contextlib
import fcntl
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

SHELF = Path(os.environ.get('DAN_ENVATO_SHELF') or Path.home() / '.dan/workspace/envato-shelf')
SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts/envato_shelf'
AE = Path('/Applications/Adobe After Effects 2027')
# One After Effects render at a time on the Mac by default. Each aerendercore takes ~9GB and 6〜7 cores; three to five
# at once (several jobs each running a pool of 3) filled the 32GB and the swap, and the screens on 3000 stopped
# answering (2026-11-25). Renders also run at a low priority so the editor's media and the chat stay quick.
SLOTS = max(1, int(os.environ.get('DAN_AE_SLOTS') or 1))
NICE = 15


def _ps():
    # A Mac busy with a render can take longer than this to list its processes: then nothing is found this time
    # (callers look again or leave things as they are). Raising here ended the very render it was checking (2026-11-27).
    try:
        out = subprocess.run(['ps', '-Ao', 'pid=,ppid=,command='], capture_output=True, text=True, timeout=30).stdout
    except subprocess.TimeoutExpired:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[0].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
    return rows


def _kill(pid):
    for sig in (15, 9):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.25)


def _cores_for(project):
    """aerendercore is started by launchd, not as aerender's child: find it by the project it renders."""
    return [pid for pid, _, cmd in _ps() if 'aerendercore' in cmd and str(project) in cmd]


def _project_of(cmd):
    return next((tok for tok in cmd.split() if tok.endswith('render.aep')), None)


def sweep_orphans():
    """Stop After Effects left behind by renders whose Python already ended. Returns the stopped pids.

    - aerender whose caller is gone (launchd adopted it, ppid 1), and the aerender it started;
    - a render core (aerendercore, always launchd's child) whose project no live aerender is rendering;
    - private workers (-m -noui) that launchd adopted.
    2026-11-25: the caller of two renders ended but its scratch folders stayed, so "the folder is gone" missed both and
    they held ~4GB with the swap full. The After Effects the owner opens on screen (no -m/-noui) is never touched."""
    rows = _ps()
    by_pid = {pid: (ppid, cmd) for pid, ppid, cmd in rows}
    wrappers = {pid for pid, _, cmd in rows if '/aerender ' in cmd + ' ' and 'aerendercore' not in cmd and '-project' in cmd}

    def adopted(pid):
        seen = set()
        while pid in wrappers and pid not in seen:
            seen.add(pid)
            ppid = by_pid[pid][0]
            if ppid == 1:
                return True
            pid = ppid
        return False

    orphans = [pid for pid in wrappers if adopted(pid)]
    live_projects = {_project_of(by_pid[pid][1]) for pid in wrappers if pid not in orphans}
    for pid, ppid, cmd in rows:
        core = 'aerendercore' in cmd and str(SHELF / 'render-') in cmd and _project_of(cmd) not in live_projects
        worker = ppid == 1 and '/Contents/MacOS/After Effects -m -noui' in cmd
        if core or worker:
            orphans.append(pid)
    for pid in orphans:
        _kill(pid)
    return orphans


def sweep_scratch(max_idle=2 * 3600):
    """Remove render-* scratch folders no After Effects process uses and nothing inside changed for max_idle seconds
    (a killed render leaves its folder behind; renders time out after 30 minutes). Returns the removed folders."""
    in_use = ' '.join(cmd for _, _, cmd in _ps())
    removed = []
    for folder in SHELF.glob('render-*'):
        if not folder.is_dir() or str(folder) in in_use:
            continue
        newest = max([folder.stat().st_mtime] + [f.stat().st_mtime for f in folder.rglob('*') if f.exists()])
        if time.time() - newest > max_idle:
            shutil.rmtree(folder, ignore_errors=True)
            removed.append(folder)
    return removed


@contextlib.contextmanager
def _slot():
    SHELF.mkdir(parents=True, exist_ok=True)
    while True:
        for i in range(SLOTS):
            f = open(SHELF / f'.ae-slot-{i}', 'w')
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                f.close()
                continue
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
                f.close()
            return
        time.sleep(2)


def _low():
    os.nice(NICE)


def _aerender(project, timeout=1800):
    proc = subprocess.Popen([AE/'aerender', '-project', project, '-rqindex', '1'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, preexec_fn=_low)
    deadline, reniced = time.monotonic() + timeout, set()
    try:
        while proc.poll() is None:
            if time.monotonic() > deadline:
                raise subprocess.TimeoutExpired(proc.args, timeout)
            for pid in _cores_for(project):
                if pid not in reniced:
                    subprocess.run(['renice', str(NICE), '-p', str(pid)], capture_output=True, timeout=5)
                    reniced.add(pid)
            time.sleep(2)
        err = proc.stderr.read().decode(errors='replace') if proc.stderr else ''
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, proc.args, stderr=err)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        # The render core outlives aerender when aerender is killed or its caller ends: stop it with the render.
        for pid in _cores_for(project):
            _kill(pid)


def catalog():
    items = json.loads((SHELF / 'catalog.json').read_text())
    removed = SHELF / 'removed'
    hidden = {p.name for p in removed.iterdir()} if removed.is_dir() else set()
    return [item for item in items if item['id'] not in hidden]


def describe(item):
    return {**{k: item[k] for k in ('id', 'group', 'name', 'duration', 'url', 'sourceName')},
            'font': item.get('font', 'SourceHanSansJP-Bold'),
            'fields': [{k: f[k] for k in ('label', 'type', 'example')} for f in item['fields']]}


def _rgb(color):
    text = str(color).strip().lstrip('#')
    if len(text) != 6:
        raise ValueError('文字の色は #rrggbb で指定してください')
    return [round(int(text[i:i+2], 16) / 255, 4) for i in (0, 2, 4)]


def resolve_style(size=None, color=None, outline=None):
    """Text size multiplier (0.5-4), #rrggbb fill colour and outline colour for a component's text."""
    scale = 1.0 if size in (None, '') else float(size)
    if not 0.5 <= scale <= 4:
        raise ValueError('文字の大きさは0.5〜4倍で指定してください')
    return scale, (_rgb(color) if color else None), (_rgb(outline) if outline else None)


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


def render(item, values, folder, *, font='SourceHanSansJP-Bold', text_scale=1.0, text_color=None, text_outline=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    # Include photo content so edits to existing photos cannot return a stale render.
    style = [] if text_scale == 1 and not text_color and not text_outline else [text_scale, text_color, text_outline]
    key = hashlib.sha256(json.dumps([item, values, font, *style], sort_keys=True).encode())
    key.update((SCRIPTS / 'prepare.jsx').read_bytes())
    for field, value in zip(item['fields'], values):
        if field['type'] in ('photo', 'photos'):
            for path in ([value] if field['type'] == 'photo' else value):
                key.update(Path(path).read_bytes())
    output = folder / (key.hexdigest() + '.mov')
    if output.is_file():
        return output
    sweep_orphans()
    with _slot(), tempfile.TemporaryDirectory(prefix='render-', dir=SHELF) as scratch:
        root = Path(scratch)
        app = AE / 'Adobe After Effects 2027.app/Contents/MacOS/After Effects'
        binary = root / 'event'
        subprocess.run(['swiftc', SCRIPTS / 'event.swift', '-o', binary], check=True, capture_output=True, timeout=90)
        # Private instances have no windows to restore. A macOS recovery dialog
        # would otherwise block startup before the worker can receive scripts.
        worker = subprocess.Popen([app, '-m', '-noui', '-ApplePersistenceIgnoreState', 'YES',
                                   '-NSQuitAlwaysKeepsWindows', 'NO'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=_low)
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
            job = dict(item=item, values=values, font=font, textScale=text_scale, textColor=text_color, textOutline=text_outline, width=1920, fps=30, mode='render',
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
                try:
                    subprocess.run([binary, str(worker.pid),
                                    'app.beginSuppressDialogs();app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);app.quit();'],
                                   capture_output=True, timeout=8)
                    worker.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    worker.terminate()
                    try:
                        worker.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        worker.kill()
                        worker.wait()
        _aerender(root/'render.aep')
        path = root/'render.mov'
        check = subprocess.check_output([shutil.which('ffprobe') or '/opt/homebrew/bin/ffprobe', '-v', 'error',
            '-select_streams','v:0','-show_entries','stream=pix_fmt,duration,width','-of','json',path],text=True)
        stream = json.loads(check)['streams'][0]
        if 'a' not in stream['pix_fmt'] or abs(float(stream['duration']) - item['duration']) > .08:
            raise RuntimeError('透明度または書き出した尺が指定と一致しません')
        os.replace(path, output)
    return output


if __name__ == '__main__':
    # launchd com.dan.ae-sweep runs this every 5 minutes; it prints only when it stopped or removed something.
    stopped, removed = sweep_orphans(), sweep_scratch()
    if stopped or removed:
        print(time.strftime('%Y-%m-%d %H:%M:%S'), 'stopped', stopped, 'removed', [f.name for f in removed], flush=True)
