"""Editable motion source revisions; rendered media is a replaceable preview."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
VERSION = '0.8.33'
IGNORED = {'node_modules', '.git', 'renders', 'snapshots', '.hyperframes', '.thumbnails', '.waveform-cache', 'proof-final', 'proof-focus', 'check.log', 'render.log', 'source-revision.json'}


def copy_source(source, destination, template=False):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not (source / 'index.html').is_file():
        raise ValueError('An editable project with index.html is required')
    if destination.is_relative_to(source):
        raise ValueError('Revision destination must be outside the source project')
    destination.mkdir(parents=True, exist_ok=False)
    for path in source.rglob('*'):
        rel = path.relative_to(source)
        if any(part in IGNORED for part in rel.parts):
            continue
        if template and (path.suffix.lower() in {'.md', '.py', '.log'} or path.name in {'verification.txt', 'shot-plan.json', 'reference-audio.m4a', 'meta.json'}):
            continue
        if path.is_symlink():
            raise ValueError('Copy linked assets into the project before rendering')
        if path.is_file():
            dest = destination / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    return destination


def prepare(room_dir, source=None, template=False):
    """Always fork: editing a new revision cannot overwrite the approved source."""
    if template:
        source = ROOT / 'videos/reference-01-finish'
    dest = Path(room_dir) / 'motion-projects' / ('work-' + uuid.uuid4().hex[:12])
    if not source:
        dest.mkdir(parents=True)
        (dest / 'assets').mkdir()
        shutil.copy2(ROOT / 'videos/reference-01-finish/assets/gsap.min.js', dest / 'assets/gsap.min.js')
        (dest / 'index.html').write_text('''<!doctype html>
<html lang="ja"><head><meta charset="UTF-8"><title>New composition</title>
<script src="assets/gsap.min.js"></script>
<style>body{margin:0}#root{position:relative;width:1280px;height:720px;overflow:hidden}.clip{position:absolute;inset:0}</style>
</head><body><div id="root" data-composition-id="main" data-start="0" data-width="1280" data-height="720" data-duration="5"></div>
<script>window.__timelines=window.__timelines||{};window.__timelines.main=gsap.timeline({paused:true});</script>
</body></html>''', encoding='utf-8')
        (dest / 'hyperframes.json').write_text('{}', encoding='utf-8')
        (dest / 'package.json').write_text(json.dumps({'name':'dan-composition','private':True,'type':'module',
            'scripts':{stage:f'npx --yes hyperframes@{VERSION} {stage}' for stage in ('check','render')}}), encoding='utf-8')
    else:
        copy_source(source, dest, template=template)
    if template:
        # Reference audio was authorized only for the comparison, not new works.
        p = dest / 'index.html'
        p.write_text(re.sub(r'<audio\b[^>]*id="reference-audio"[\s\S]*?</audio>', '', p.read_text(encoding='utf-8')), encoding='utf-8')
        (dest / 'assets/reference-audio.m4a').unlink(missing_ok=True)
    return {'ok': True, 'project_dir': str(dest), 'entry': str(dest / 'index.html'),
            'note': 'Edit the source with normal file tools, including canvas size and duration for this work. Render with render_motion_project. New projects have no imposed style; templates carry reusable visuals, not previous briefs or comparison audio.'}


def write_file(room_dir, project_dir, relative_path, content):
    """Write source directly as UTF-8, without nested shell quoting or codepages."""
    root = (Path(room_dir) / 'motion-projects').resolve()
    project = Path(project_dir).resolve()
    if project == root or not project.is_relative_to(root) or not (project / 'index.html').is_file():
        raise ValueError('Prepare a working project in this room first')
    relative = Path(relative_path)
    target = (project / relative).resolve()
    if relative.is_absolute() or target == project or not target.is_relative_to(project):
        raise ValueError('Source path must stay inside the working project')
    if not isinstance(content, str):
        raise ValueError('Source content must be text')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(content, encoding='utf-8')
    temporary.replace(target)
    return {'ok': True, 'path': str(target), 'bytes': len(content.encode('utf-8')),
            'note': 'Source saved exactly as supplied. Render and inspect before placing the result.'}


def project_version(project):
    package = Path(project) / 'package.json'
    if not package.is_file():
        return VERSION
    scripts = json.loads(package.read_text(encoding='utf-8-sig')).get('scripts', {})
    pins = {match.group(1) for name in ('check', 'render')
            if (match := re.search(r'\bhyperframes@(\d+\.\d+\.\d+)\b', str(scripts.get(name, ''))))}
    if len(pins) > 1:
        raise ValueError('Check and render must use the same HyperFrames version')
    return next(iter(pins), VERSION)


def _npx_cli(node):
    """npm's npx entry beside node: Windows keeps it next to node.exe, Homebrew under lib/."""
    candidates = []
    for base in dict.fromkeys([Path(node).parent, Path(node).resolve().parent]):
        candidates += [base / 'node_modules/npm/bin/npx-cli.js', base.parent / 'lib/node_modules/npm/bin/npx-cli.js']
    return next((c for c in candidates if c.is_file()), None)


def _npx_caches():
    caches = [Path.home() / '.npm/_npx']
    if os.environ.get('npm_config_cache'):
        caches.insert(0, Path(os.environ['npm_config_cache']) / '_npx')
    if os.environ.get('LOCALAPPDATA'):
        caches.append(Path(os.environ['LOCALAPPDATA']) / 'npm-cache/_npx')
    caches.append(Path.home() / 'AppData/Local/npm-cache/_npx')
    return list(dict.fromkeys(caches))


def hyperframes_command(version):
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node.js is unavailable')
    # Use the verified installed CLI directly. npm otherwise rechecks its registry
    # on every edit, which can stall inside a production worker's environment.
    for cache in _npx_caches():
        for package in cache.glob('*/node_modules/hyperframes/package.json'):
            try:
                if json.loads(package.read_text(encoding='utf-8')).get('version') == version:
                    entry = package.parent / 'bin/hyperframes.mjs'
                    if entry.is_file():
                        return [node, str(entry)]
            except (OSError, ValueError):
                continue
    npx = _npx_cli(node)
    if npx:
        return [node, str(npx), '--yes', 'hyperframes@' + version]
    npx = shutil.which('npx')
    if npx:
        return [npx, '--yes', 'hyperframes@' + version]
    raise RuntimeError('npm npx is unavailable')


def composition_seconds(project):
    html = (Path(project) / 'index.html').read_text(encoding='utf-8', errors='replace')
    match = re.search(r'data-composition-id="main"[^>]*?data-duration="([\d.]+)"', html) or re.search(r'data-duration="([\d.]+)"', html)
    try:
        return float(match.group(1)) if match else 30.0
    except ValueError:
        return 30.0


def render_workers():
    return max(1, min(4, (os.cpu_count() or 2) // 3))


def render(room_dir, project_dir, ffmpeg):
    source = Path(project_dir).resolve()
    revision = Path(room_dir) / 'motion-revisions' / uuid.uuid4().hex
    copy_source(source, revision)
    version = project_version(revision)
    manifest = {str(p.relative_to(revision)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in revision.rglob('*') if p.is_file()}
    source_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    command = hyperframes_command(version)
    env = os.environ.copy()
    env['PATH'] = str(Path(ffmpeg).parent) + os.pathsep + env.get('PATH', '')
    started = time.monotonic()
    seconds = composition_seconds(revision)
    workers = render_workers()
    # Rendering time grows with length; a fixed limit killed ordinary 18-second works.
    timeout = int(180 + seconds * 30)
    for stage, args in [('check', ['check']), ('render', ['render', '--workers', str(workers), '--quality', 'high', '-o', 'renders/video.mp4'])]:
        log = revision / (stage + '.log')
        with log.open('w', encoding='utf-8') as output:
            result = subprocess.run([*command, *args], cwd=revision,
                                    env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, timeout=timeout,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError(f'{stage} failed: {log}\n' + log.read_text(encoding='utf-8')[-5000:])
    output = revision / 'renders/video.mp4'
    if not output.is_file() or not output.stat().st_size:
        raise RuntimeError('Rendering produced no video')
    provenance = {'engine': 'hyperframes', 'engine_version': version, 'project_dir': str(revision),
                  'source_hash': source_hash, 'source_files': manifest, 'elapsed_seconds': round(time.monotonic()-started, 2)}
    (revision / 'source-revision.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    return output, provenance
