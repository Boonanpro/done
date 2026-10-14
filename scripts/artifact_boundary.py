"""Keep one site's own code out of Dan's repository (owner, 2026-10-15).

Dan is given to other people; the sites Dan builds for the owner are not part of it. A site's pages live in
frontend/src/app/artifacts/<slug>/ and its server routes in artifacts/<slug>/_server/ (mounted by
app/services/artifact_backends.py). Both are kept in Git with the site (done-artifacts), never in Dan.

On 2026-10-14 the X operation room's API was written into app/api/ and frontend/src/app/api/x-operation/ instead,
where no repository kept it. This module finds that kind of leak:

- a new file under frontend/src/app/api/<dir>/ other than api/v1 (a site's own Next route belongs in its artifact),
- a Dan file named after a site (app/api/x_operation_routes.py),
- a line that pins Dan's code to one site: a fixed room ID constant, a dedicated site host (dan-site-...vercel.app),
  or a path into one site (/preview/<slug>, artifacts/<slug>/).

Used by the pre-commit hook and CI on added lines only, and by artifact_archive's hourly sweep on the whole working
tree (uncommitted files included) against the recorded list of older cases in artifact_boundary_known.txt.
A line that has to name a site anyway is marked with `artifact-boundary: ok`.

    python scripts/artifact_boundary.py --working        # every case in the working tree, known ones marked
    python scripts/artifact_boundary.py --staged         # what the pre-commit hook checks
    python scripts/artifact_boundary.py --diff A B       # what CI checks
"""
from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT/'frontend'/'src'/'app'/'artifacts'
KNOWN = Path(__file__).with_name('artifact_boundary_known.txt')
OK_MARK = 'artifact-boundary: ok'
# Dan's own directories inside the artifacts route group (not sites).
NOT_SLUGS = {'[slug]', '_seo', 'publish', 'layout.tsx'}
API_SHARED = {'v1', 'public'}
SOURCE = re.compile(r'\.(py|ts|tsx|js|mjs)$')
ROOM_CONSTANT = re.compile(r'\b\w*ROOM\w*\s*[:=]\s*["\'][0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}["\']',
                           re.I)
SITE_HOST = re.compile(r'\bdan-site-[a-z0-9-]+-[0-9a-f]{8}\.vercel\.app')


@dataclass(frozen=True)
class Finding:
    path: str
    reason: str
    line: str = ''

    @property
    def key(self) -> str:
        return f'{self.path} | {self.reason}'


def site_slugs(root: Path | None = None) -> set[str]:
    """Sites on this PC. Commits are made from worktrees, which do not carry the (untracked) sites: read the live tree."""
    if root is None:
        common = _git('rev-parse', '--path-format=absolute', '--git-common-dir').strip()
        root = Path(common).parent/'frontend'/'src'/'app'/'artifacts' if common else ARTIFACTS
    if not root.is_dir():
        return set()
    return {p.name for p in root.iterdir() if p.is_dir() and p.name not in NOT_SLUGS and not p.name.startswith('_')}


def guarded(path: str) -> bool:
    """Dan's own code that must not carry one site's logic."""
    p = path.replace('\\', '/')
    if not SOURCE.search(p) or '.generated.' in p:   # generated maps (custom domains, sitemaps) list every site
        return False
    if p.startswith(('app/', 'services/', 'frontend/src/lib/', 'frontend/src/components/', 'frontend/src/hooks/',
                     'frontend/src/stores/', 'frontend/src/app/api/v1/')):
        return True
    return p in ('frontend/src/middleware.ts',) or p.startswith('frontend/next.config.')


def api_dir(path: str) -> str | None:
    p = path.replace('\\', '/')
    if p.startswith('frontend/src/app/api/'):
        head = p[len('frontend/src/app/api/'):].split('/', 1)[0]
        if head and head not in API_SHARED and '/' in p[len('frontend/src/app/api/'):]:
            return head
    return None


def path_findings(path: str, slugs: set[str], added: bool = True) -> list[Finding]:
    """Placement of a new file (changes to older files are judged by their lines)."""
    p = path.replace('\\', '/')
    found = []
    if not added:
        return found
    head = api_dir(p)
    if head:
        found.append(Finding(p, f'site API under frontend/src/app/api/{head}/ (put it in artifacts/<slug>/)'))
    if guarded(p):
        stem = Path(p).stem.lower()
        for slug in slugs:
            token = slug.replace('-', '_')
            if len(token) >= 6 and (stem == token or stem.startswith(token + '_')):
                found.append(Finding(p, f'Dan file named after site {slug}'))
    return found


def line_findings(path: str, line: str, slugs: set[str]) -> list[Finding]:
    if OK_MARK in line or not guarded(path):
        return []
    found = []
    if ROOM_CONSTANT.search(line):
        found.append(Finding(path, 'fixed room ID constant', line.strip()[:160]))
    if SITE_HOST.search(line):
        found.append(Finding(path, 'dedicated site host', line.strip()[:160]))
    for slug in slugs:
        if re.search(r'(/preview/|artifacts/)' + re.escape(slug) + r'(?![\w-])', line):
            found.append(Finding(path, f'path into site {slug}', line.strip()[:160]))
    return found


def _git(*args: str) -> str:
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                          errors='replace').stdout


def diff_findings(diff_args: list[str], slugs: set[str]) -> list[Finding]:
    """Findings on added files and added lines of a git diff."""
    found: list[Finding] = []
    for row in _git('diff', '--name-status', '--diff-filter=ACMRT', *diff_args).splitlines():
        status, *names = row.split('\t')
        found += path_findings(names[-1], slugs, added=status[0] in 'ACR')
    path = None
    for line in _git('diff', '-U0', '--diff-filter=ACMRT', *diff_args).splitlines():
        if line.startswith('+++ '):
            path = line[6:] if line.startswith('+++ b/') else None
        elif line.startswith('+') and path:
            found += line_findings(path, line[1:], slugs)
    return found


def tree_findings(slugs: set[str]) -> list[Finding]:
    """Every case in the working tree, uncommitted and untracked files included."""
    files = _git('ls-files', '--cached', '--others', '--exclude-standard').splitlines()
    files += _git('ls-files', '--others', '--ignored', '--exclude-standard', 'frontend/src/app/api').splitlines()
    found: list[Finding] = []
    for path in sorted(set(files)):
        found += path_findings(path, slugs)
        if guarded(path):
            try:
                text = (ROOT/path).read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            seen = set()
            for line in text.splitlines():
                for f in line_findings(path, line, slugs):
                    if f.reason not in seen:   # one entry per file and reason
                        seen.add(f.reason)
                        found.append(f)
    return found


def known() -> set[str]:
    if not KNOWN.exists():
        return set()
    return {l.strip() for l in KNOWN.read_text(encoding='utf-8').splitlines() if l.strip() and not l.startswith('#')}


def report(findings: list[Finding], out) -> None:
    out.write('\n' + '=' * 70 + '\n')
    out.write('ダン本体に、成果物（作ったサイト・ツール）専用の処理が入っています\n')
    out.write('=' * 70 + '\n')
    for f in findings:
        out.write(f'  {f.path}: {f.reason}\n')
        if f.line:
            out.write(f'      {f.line}\n')
    out.write('\n置き場所:\n'
              '  ・画面とNextのルート: frontend/src/app/artifacts/<slug>/（例: artifacts/<slug>/editorial/route.ts）\n'
              '  ・Pythonの裏側の処理: frontend/src/app/artifacts/<slug>/_server/routes.py（router を定義すると\n'
              '    app/services/artifact_backends.py が /api/v1 に載せる）\n'
              '  どちらも公開・1時間ごとに done-artifacts へ保存される。ダン本体には汎用の部分だけ置く。\n'
              '  どうしても名前を書く行には「artifact-boundary: ok」を書き添える。\n')


def main() -> int:
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--staged', action='store_true')
    mode.add_argument('--diff', nargs=2, metavar=('BASE', 'HEAD'))
    mode.add_argument('--working', action='store_true')
    args = parser.parse_args()
    slugs = site_slugs()
    if args.working:
        old = known()
        for f in tree_findings(slugs):
            print(('  known ' if f.key in old else '  NEW   ') + f.key)
        return 0
    found = diff_findings(['--cached'] if args.staged else [f'{args.diff[0]}...{args.diff[1]}'], slugs)
    if found:
        report(found, sys.stdout)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
