"""The auto-install hooks act on the frontend the edited file belongs to, and leave the running folder's tracked files
alone (2026-10-18): a package installed for an artifact there is not saved to package.json, a missing shared ui part
is not added there."""
import importlib.util
import io
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tree(root, page_text):
    (root / 'frontend' / 'src' / 'components' / 'ui').mkdir(parents=True)
    (root / 'frontend' / 'package.json').write_text('{"dependencies": {}}')
    page = root / 'frontend' / 'src' / 'app' / 'artifacts' / 'shop' / 'page.tsx'
    page.parent.mkdir(parents=True)
    page.write_text(page_text)
    return page


def run(mod, monkeypatch, page):
    calls = []
    monkeypatch.setattr(mod, 'install', lambda name: (calls.append((name, mod.FRONTEND_DIR)) or (True, '')))
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({'tool_input': {'file_path': str(page)}})))
    err = io.StringIO()
    monkeypatch.setattr(sys, 'stderr', err)
    mod.main()
    return calls, err.getvalue()


def test_npm_in_a_worktree_installs_there_and_saves(tmp_path, monkeypatch):
    npm = load('hook_autoinstall_npm')
    monkeypatch.setattr(npm, 'PROJECT_ROOT', tmp_path / 'done')
    page = tree(tmp_path / 'wt', 'import { format } from "date-fns";\n')
    calls, _ = run(npm, monkeypatch, page)
    assert calls == [('date-fns', tmp_path / 'wt' / 'frontend')] and npm.NO_SAVE is False


def test_npm_in_the_running_folder_does_not_save(tmp_path, monkeypatch):
    npm = load('hook_autoinstall_npm')
    monkeypatch.setattr(npm, 'PROJECT_ROOT', tmp_path / 'done')
    page = tree(tmp_path / 'done', 'import { format } from "date-fns";\n')
    calls, err = run(npm, monkeypatch, page)
    assert calls and npm.NO_SAVE is True and 'package.json is not changed' in err


def test_shadcn_in_the_running_folder_adds_nothing(tmp_path, monkeypatch):
    sh = load('hook_autoinstall_shadcn')
    monkeypatch.setattr(sh, 'PROJECT_ROOT', tmp_path / 'done')
    page = tree(tmp_path / 'done', 'import { Accordion } from "@/components/ui/accordion";\n')
    calls, err = run(sh, monkeypatch, page)
    assert calls == [] and 'accordion' in err and 'work.py' in err


def test_shadcn_in_a_worktree_adds_there(tmp_path, monkeypatch):
    sh = load('hook_autoinstall_shadcn')
    monkeypatch.setattr(sh, 'PROJECT_ROOT', tmp_path / 'done')
    page = tree(tmp_path / 'wt', 'import { Accordion } from "@/components/ui/accordion";\n')
    calls, _ = run(sh, monkeypatch, page)
    assert calls == [('accordion', tmp_path / 'wt' / 'frontend')]



def test_artifact_packages_survive_the_next_install(tmp_path, monkeypatch):
    """A package installed for an artifact stays when another one is installed later, and when follow_github installs
    a changed package.json (2026-10-18 check: npm pruned the earlier --no-save package)."""
    npm = load('hook_autoinstall_npm')
    front = tmp_path / 'done' / 'frontend'
    front.mkdir(parents=True)
    (front / 'package.json').write_text('{"dependencies": {}}')
    calls = []

    def fake_npm(where, args):
        calls.append(args)
        # npm keeps exactly what package.json and the names given ask for
        for d in (where / 'node_modules').glob('*') if (where / 'node_modules').exists() else []:
            if d.name not in args:
                import shutil; shutil.rmtree(d)
        for name in args[2:]:
            (where / 'node_modules' / name).mkdir(parents=True, exist_ok=True)
            (where / 'node_modules' / name / 'package.json').write_text('{}')
        return True, ''
    monkeypatch.setattr(npm, '_npm', fake_npm)
    assert npm.install_live(front, ['date-fns'])[0]
    assert npm.install_live(front, ['recharts'])[0]
    assert (front / 'node_modules' / 'date-fns').is_dir() and (front / 'node_modules' / 'recharts').is_dir()
    assert calls[-1] == ['install', '--no-save', 'date-fns', 'recharts']
    assert npm.install_live(front)[0]                                    # what follow_github does
    assert (front / 'node_modules' / 'date-fns').is_dir()
    npm.FRONTEND_DIR, npm.PACKAGE_JSON = front, front / 'package.json'
    assert {'date-fns', 'recharts'} <= npm.installed_packages()


def test_a_package_named_but_not_present_is_installed(tmp_path, monkeypatch):
    """Named in package.json is not enough: it must be in node_modules (2026-10-18 check)."""
    npm = load('hook_autoinstall_npm')
    monkeypatch.setattr(npm, 'PROJECT_ROOT', tmp_path / 'done')
    page = tree(tmp_path / 'wt', 'import { format } from "date-fns";\n')
    (tmp_path / 'wt' / 'frontend' / 'package.json').write_text('{"dependencies": {"date-fns": "^4"}}')
    calls, _ = run(npm, monkeypatch, page)
    assert calls == [('date-fns', tmp_path / 'wt' / 'frontend')]
