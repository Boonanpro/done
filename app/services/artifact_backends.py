"""Server routes that belong to one site live with that site, not in Dan (owner, 2026-10-15).

A site under frontend/src/app/artifacts/<slug>/ may carry its own API in `_server/` (a package with `routes.py` that
defines a FastAPI `router`). That folder is the site's source and is kept in Git with it (done-artifacts), so Dan's own
repository holds no single user's business code. The sandbox mounts every such router under /api/v1 at startup.
Dan without those sites mounts nothing; a site whose code fails to load is logged and skipped, never taking the
sandbox down with it."""
import importlib
import importlib.util
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
ARTIFACTS = Path(__file__).resolve().parents[2]/'frontend'/'src'/'app'/'artifacts'
failures: dict[str, str] = {}


def module_name(slug):
    return 'dan_artifact_' + re.sub(r'\W', '_', slug)


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
        for key in [k for k in sys.modules if k == name or k.startswith(name + '.')]:
            sys.modules.pop(key, None)
        raise


def routers():
    """(slug, router) for every site that has server routes."""
    found = []
    for routes in sorted(ARTIFACTS.glob('*/_server/routes.py')) if ARTIFACTS.is_dir() else []:
        slug = routes.parent.parent.name
        try:
            found.append((slug, load(slug).router))
            failures.pop(slug, None)
        except Exception as exc:  # noqa: BLE001 - one site's broken code must not stop Dan
            failures[slug] = f'{type(exc).__name__}: {exc}'
            logger.exception('artifact server routes failed to load: %s', slug)
    return found
