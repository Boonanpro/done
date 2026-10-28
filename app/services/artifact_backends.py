"""Server routes that belong to one site live with that site, not in Dan (owner, 2026-10-15).

A site under frontend/src/app/artifacts/<slug>/ may carry its own API in `_server/` (a package with `routes.py` that
defines a FastAPI `router`). That folder is the site's source and is kept in Git with it (done-artifacts), so Dan's own
repository holds no single user's business code. The sandbox mounts every such router under /api/v1 at startup.
Dan without those sites mounts nothing; a site whose code fails to load is logged and skipped, never taking the
sandbox down with it.

Reloading without a restart (owner, 2026-10-18: "what you fixed and what I operate must never differ"). The page of a
site follows its files within seconds, but this sandbox runs without --reload, so a changed `_server` used to wait for a
restart of Dan; meanwhile the owner saw new buttons served by old server code. The live sandbox (port 8000) now watches
every `_server` folder and swaps that site's routes in place when its files change. A site that starts background
work (a thread) must define `dan_unload()` in routes.py to stop it; the old module's work is stopped before the new
module is imported, which starts its own again. A site with live threads and no `dan_unload` is not swapped: two
copies of a patrol would send everything twice. Its state says a restart is needed instead.

What runs is written to `.tmp/artifact-backends.json` (per site: the fingerprint of the files on disk, the fingerprint
of the code that runs, state and reason). `scripts/artifact_seen.py` and the page's version check
(`frontend/src/app/dan-live/version`) read it, so a server that is behind its files is reported as behind."""
import asyncio
import hashlib
import importlib
import importlib.util
import json
import logging
import os
import py_compile
import re
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = Path(os.environ.get('DAN_ARTIFACTS_DIR') or ROOT/'frontend'/'src'/'app'/'artifacts')
STATE_FILE = Path(os.environ.get('DAN_ARTIFACT_BACKENDS_STATE') or ROOT/'.tmp'/'artifact-backends.json')
LIVE_PORT = 8000
SCAN_S = 1.5
HEARTBEAT_S = 30
failures: dict[str, str] = {}
_mounted: dict[str, dict] = {}   # slug -> {'routes': [...], 'module': routes module, 'loaded': fingerprint}
_state: dict[str, dict] = {}
_lock = threading.RLock()
_app = None
_prefix = '/api/v1'
_loop = None
_started = False


def module_name(slug):
    return 'dan_artifact_' + re.sub(r'\W', '_', slug)


def server_files(slug):
    """Files of <slug>/_server that make up its code (caches excluded), in a stable order."""
    base = ARTIFACTS/slug/'_server'
    if not base.is_dir():
        return []
    return sorted((p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'),
                  key=lambda p: p.relative_to(base).as_posix())


def fingerprint(slug):
    """sha1 over relative path + content of every file. The same recipe is in artifact_seen.py and dan-live/version."""
    base = ARTIFACTS/slug/'_server'
    h = hashlib.sha1()
    for p in server_files(slug):
        try:
            data = p.read_bytes()
        except OSError:
            continue
        h.update(p.relative_to(base).as_posix().encode('utf-8') + b'\0' + data + b'\0')
    return h.hexdigest()[:12]


def _drop_modules(name):
    removed = {k: sys.modules.pop(k) for k in [k for k in sys.modules if k == name or k.startswith(name + '.')]}
    return removed


def load(slug):
    """Import <slug>/_server as a package and return its routes module."""
    name = module_name(slug)
    if name + '.routes' in sys.modules:
        return sys.modules[name + '.routes']
    package = ARTIFACTS/slug/'_server'
    spec = importlib.util.spec_from_file_location(name, package/'__init__.py', submodule_search_locations=[str(package)])
    if spec is None or spec.loader is None:
        raise ImportError(f'{package} has no __init__.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        return importlib.import_module(name + '.routes')
    except BaseException:
        _drop_modules(name)
        raise


def slugs():
    return [p.parent.parent.name for p in sorted(ARTIFACTS.glob('*/_server/routes.py'))] if ARTIFACTS.is_dir() else []


def routers():
    """(slug, router) for every site that has server routes."""
    found = []
    for slug in slugs():
        try:
            found.append((slug, load(slug).router))
            failures.pop(slug, None)
        except Exception as exc:  # noqa: BLE001 - one site's broken code must not stop Dan
            failures[slug] = f'{type(exc).__name__}: {exc}'
            logger.exception('artifact server routes failed to load: %s', slug)
    return found


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _set(slug, **fields):
    with _lock:
        row = _state.setdefault(slug, {})
        row.update(fields)
        row['at'] = _now()


def _include(slug, router):
    """Add the site's routes to the app and remember which route objects are the site's."""
    routes = _app.router.routes
    before = len(routes)
    _app.include_router(router, prefix=_prefix)
    added = routes[before:]
    return list(added)


def mount(app, prefix='/api/v1'):
    """Mount every site's routes at startup (replaces the plain include loop in sandbox/main.py)."""
    global _app, _prefix
    _app, _prefix = app, prefix
    for slug in slugs():
        files = fingerprint(slug)
        try:
            module = load(slug)
            added = _include(slug, module.router)
            _mounted[slug] = {'routes': added, 'module': module, 'loaded': files}
            failures.pop(slug, None)
            _set(slug, files=files, loaded=files, state='current', reason='', error='')
        except Exception as exc:  # noqa: BLE001 - one site's broken code must not stop Dan
            failures[slug] = f'{type(exc).__name__}: {exc}'
            logger.exception('artifact server routes failed to load: %s', slug)
            _set(slug, files=files, loaded='', state='failed', reason='load-error', error=failures[slug][:300])


def _threads_of(module_prefix):
    out = []
    for t in threading.enumerate():
        target = getattr(t, '_target', None)
        mod = getattr(target, '__module__', '') or ''
        if t.is_alive() and (mod == module_prefix or mod.startswith(module_prefix + '.')):
            out.append(t)
    return out


def _compile_all(slug):
    for p in server_files(slug):
        if p.suffix == '.py':
            py_compile.compile(str(p), cfile=os.path.join(tempfile.gettempdir(), 'dan_artifact_check.pyc'), doraise=True)


def _clear_bytecode(slug):
    """Python trusts a cached .pyc whose source has the same size and mtime second; a quick edit can match both."""
    for p in (ARTIFACTS/slug/'_server').rglob('__pycache__/*.pyc'):
        try:
            p.unlink()
        except OSError:
            pass


def _swap_routes(old, new):
    """Replace the site's old route objects with the new ones at the same place, on the server's own loop so no
    request sees a half-changed list."""
    def apply():
        routes = _app.router.routes
        idx = [i for i, r in enumerate(routes) if any(r is o for o in old)]
        for i in reversed(idx):
            del routes[i]
        for r in new:
            routes.remove(r)
        at = idx[0] if idx else len(routes)
        routes[at:at] = new
        _app.openapi_schema = None
    if _loop is None or not _loop.is_running():
        apply()
        return
    done = threading.Event()
    error = []

    def run():
        try:
            apply()
        except BaseException as e:  # noqa: BLE001
            error.append(e)
        finally:
            done.set()
    _loop.call_soon_threadsafe(run)
    if not done.wait(10):
        raise TimeoutError('route swap did not run on the server loop')
    if error:
        raise error[0]


def reload(slug):
    """Swap one site's server code for what is on disk now. Returns the new state."""
    with _lock:
        files = fingerprint(slug)
        entry = _mounted.get(slug)
        if entry and entry['loaded'] == files:
            _set(slug, files=files, state='current', reason='', error='')
            return _state[slug]
        _set(slug, files=files, state='reloading', reason='', error='')
        name = module_name(slug)
        try:
            _compile_all(slug)
        except Exception as exc:  # noqa: BLE001 - keep the old code running
            _set(slug, state='failed', reason='syntax-error', error=f'{type(exc).__name__}: {exc}'[:300])
            return _state[slug]
        old_module = entry['module'] if entry else None
        if old_module is not None:
            unload = getattr(old_module, 'dan_unload', None)
            if callable(unload):
                try:
                    unload()
                except Exception as exc:  # noqa: BLE001
                    logger.exception('dan_unload failed: %s', slug)
                    _set(slug, state='needs-restart', reason='unload-failed', error=f'{type(exc).__name__}: {exc}'[:300])
                    return _state[slug]
            left = _threads_of(name)
            if left:
                _set(slug, state='needs-restart', reason='background-thread',
                     error=('裏で動き続ける処理があり止め方（routes.py の dan_unload）が無いため、本体の再起動が要る: '
                            + ', '.join(t.name for t in left))[:300])
                return _state[slug]
        saved = _drop_modules(name)
        _clear_bytecode(slug)
        try:
            module = load(slug)
            new_routes = _include(slug, module.router)
            _swap_routes(entry['routes'] if entry else [], new_routes)
        except Exception as exc:  # noqa: BLE001 - keep serving the old routes
            logger.exception('artifact server reload failed: %s', slug)
            _drop_modules(name)
            sys.modules.update(saved)
            failures[slug] = f'{type(exc).__name__}: {exc}'
            restarted = ''
            if old_module is not None and callable(getattr(old_module, 'dan_unload', None)):
                restarted = '（古い版の裏の処理は止まっている）'
            _set(slug, state='failed', reason='load-error', error=(failures[slug] + restarted)[:300])
            return _state[slug]
        failures.pop(slug, None)
        _mounted[slug] = {'routes': new_routes, 'module': module, 'loaded': files}
        _set(slug, files=files, loaded=files, state='current', reason='', error='', reloaded_at=_now())
        logger.info('artifact server reloaded: %s (%s)', slug, files)
        return _state[slug]


def write_state():
    with _lock:
        data = {'pid': os.getpid(), 'heartbeat': _now(), 'started': _started_at, 'sites': dict(_state)}
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_name(f'{STATE_FILE.name}.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, STATE_FILE)
    except OSError:
        logger.exception('artifact backend state write failed')


_started_at = _now()


def _watch():
    seen: dict[str, str] = {}
    last_beat = 0.0
    while True:
        try:
            changed = False
            present = set(slugs())
            for slug in sorted(present | set(_mounted)):
                if slug not in present:
                    continue   # a removed site keeps its old routes until a restart; nothing to compare
                files = fingerprint(slug)
                entry = _mounted.get(slug)
                loaded = entry['loaded'] if entry else ''
                if files == loaded:
                    if _state.get(slug, {}).get('state') != 'current':
                        _set(slug, files=files, state='current', reason='', error='')
                        changed = True
                    seen[slug] = files
                    continue
                if seen.get(slug) != files:
                    # still being written: wait until two scans agree
                    seen[slug] = files
                    if _state.get(slug, {}).get('files') != files:
                        _set(slug, files=files, state='reloading', reason='', error='')
                        changed = True
                    continue
                st = _state.get(slug, {})
                if st.get('state') in ('failed', 'needs-restart') and st.get('files') == files and st.get('tried') == files:
                    continue   # already tried this exact code
                reload(slug)
                _set(slug, tried=files)
                changed = True
            if changed or time.time() - last_beat > HEARTBEAT_S:
                write_state()
                last_beat = time.time()
        except Exception:  # noqa: BLE001 - the watcher must keep running
            logger.exception('artifact backend watcher failed')
        time.sleep(SCAN_S)


def _port_from_argv():
    argv = sys.argv
    for i, a in enumerate(argv):
        if a == '--port' and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith('--port='):
            return a.split('=', 1)[1]
    return ''


def start_watcher():
    """Called from the sandbox's lifespan. The live sandbox (8000) watches and writes the state file; a test
    server can opt in with DAN_ARTIFACT_RELOAD=1 (and its own DAN_ARTIFACT_BACKENDS_STATE).

    A release worker's sandbox (DAN_GENERATION, scripts/core_release.py) watches too, into its own state file. The
    gateway sends every route the release mounted at its start to that sandbox, a site's routes included, and a
    site's files are shared with the live folder, not part of the release. Without its own watcher a fixed
    `_server` reached 8000 within seconds but the page kept talking to the release's copy loaded at its start
    (2026-10-28: the customer page's new routes never reached the owner until the next Core restart)."""
    global _loop, _started, STATE_FILE
    if _started or _app is None:
        return False
    generation = os.environ.get('DAN_GENERATION', '')
    if os.environ.get('DAN_ARTIFACT_RELOAD') != '1' and _port_from_argv() != str(LIVE_PORT) and not generation:
        return False
    if generation and not os.environ.get('DAN_ARTIFACT_BACKENDS_STATE'):
        # never overwrite the live sandbox's file, which artifact_seen and the release badge read
        safe = re.sub(r'[^\w.-]', '_', generation)
        STATE_FILE = STATE_FILE.with_name(f'artifact-backends.{safe}.json')
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        _loop = None
    _started = True
    write_state()
    threading.Thread(target=_watch, name='artifact-backend-watch', daemon=True).start()
    return True
