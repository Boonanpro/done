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
VERSION = '0.8.31'
IGNORED = {'node_modules', '.git', 'renders', 'snapshots', '.hyperframes', 'proof-final', 'proof-focus', 'check.log', 'render.log', 'source-revision.json'}


def copy_source(source, destination):
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
    if not source:
        raise ValueError('Provide an existing project or choose the approved optical-type template')
    dest = Path(room_dir) / 'motion-projects' / ('work-' + uuid.uuid4().hex[:12])
    copy_source(source, dest)
    if template:
        # Reference audio was authorized only for the comparison, not new works.
        p = dest / 'index.html'
        p.write_text(re.sub(r'<audio\b[^>]*id="reference-audio"[\s\S]*?</audio>', '', p.read_text(encoding='utf-8')), encoding='utf-8')
        (dest / 'assets/reference-audio.m4a').unlink(missing_ok=True)
    return {'ok': True, 'project_dir': str(dest), 'entry': str(dest / 'index.html'),
            'note': 'Edit the source with normal file tools. Render with render_motion_project. Template comparison audio is removed.'}


def render(room_dir, project_dir, ffmpeg):
    source = Path(project_dir).resolve()
    revision = Path(room_dir) / 'motion-revisions' / uuid.uuid4().hex
    copy_source(source, revision)
    manifest = {str(p.relative_to(revision)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in revision.rglob('*') if p.is_file()}
    source_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node.js is unavailable')
    npx = Path(node).parent / 'node_modules/npm/bin/npx-cli.js'
    if not npx.is_file():
        raise RuntimeError('npm npx-cli.js is unavailable')
    env = os.environ.copy()
    # Use the verified installed CLI directly. npm otherwise rechecks its registry
    # on every edit, which can stall inside a production worker's environment.
    command = [node, str(npx), '--yes', 'hyperframes@' + VERSION]
    cache = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'npm-cache/_npx'
    for package in cache.glob('*/node_modules/hyperframes/package.json'):
        try:
            if json.loads(package.read_text(encoding='utf-8')).get('version') == VERSION:
                entry = package.parent / 'bin/hyperframes.mjs'
                if entry.is_file():
                    command = [node, str(entry)]
                    break
        except (OSError, ValueError):
            continue
    env['PATH'] = str(Path(ffmpeg).parent) + os.pathsep + env.get('PATH', '')
    started = time.monotonic()
    for stage, args in [('check', ['check']), ('render', ['render', '--workers', '1', '--quality', 'high', '-o', 'renders/video.mp4'])]:
        log = revision / (stage + '.log')
        with log.open('w', encoding='utf-8') as output:
            result = subprocess.run([*command, *args], cwd=revision,
                                    env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, timeout=180,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError(f'{stage} failed: {log}\n' + log.read_text(encoding='utf-8')[-5000:])
    output = revision / 'renders/video.mp4'
    if not output.is_file() or not output.stat().st_size:
        raise RuntimeError('Rendering produced no video')
    provenance = {'engine': 'hyperframes', 'engine_version': VERSION, 'project_dir': str(revision),
                  'source_hash': source_hash, 'source_files': manifest, 'elapsed_seconds': round(time.monotonic()-started, 2)}
    (revision / 'source-revision.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    return output, provenance
