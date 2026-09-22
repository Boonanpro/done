"""Build's editable-page workflow: scaffold, browser audit, reviewed registration.

The calling agent designs/reconstructs page-body.tsx from the brief and images.
This tool wires the ordinary artifact/editor contract and verifies native copy;
it never claims that structural checks judge visual quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'frontend'
SLUG = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')


def artifact_dir(slug: str, root: Path = ROOT) -> Path:
    if not SLUG.fullmatch(slug) or len(slug) > 80 or slug in {'publish'}:
        raise ValueError('slug must contain lowercase letters, numbers and hyphens')
    return root / 'frontend/src/app/artifacts' / slug


def write_json(path: Path, value: object):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def scaffold(slug: str, title: str, root: Path = ROOT) -> dict:
    target = artifact_dir(slug, root)
    if target.exists():
        raise ValueError(f'{target} already exists; update its source without replacing saved releases')
    target.mkdir(parents=True)
    (target / 'page.tsx').write_text(
        "import { EditableProvider } from '@/components/dan/editable';\n"
        "import { toEditableOverrides, type ReleaseOverrides } from '@/lib/editable-release';\n"
        "import { PageBody } from './page-body';\n"
        "import release from './release.gen.json';\n\n"
        f"export const metadata = {{ title: {json.dumps(title, ensure_ascii=False)} }};\n"
        "export default function Page() {\n"
        "  return <EditableProvider overrides={toEditableOverrides(release as ReleaseOverrides)}>\n"
        f'    <div data-dan-artifact="{slug}"><PageBody /></div>\n'
        "  </EditableProvider>;\n}\n", encoding='utf-8')
    (target / 'page-body.tsx').write_text(
        "'use client';\n\n"
        "// Replace this scaffold with the actual design. Audit will reject an empty page.\n"
        "export function PageBody() { return <main />; }\n", encoding='utf-8')
    write_json(target / 'release.gen.json', {})
    write_json(target / 'editable-artifact.json', {
        'version': 1, 'slug': slug, 'title': title, 'requiredText': [], 'references': [],
    })
    return {'directory': str(target), 'page': str(target / 'page.tsx'),
            'next': 'Implement page-body.tsx and fill requiredText/references; then audit.'}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_fingerprint(target: Path, extra_files: list[str]) -> dict[str, str]:
    """Include transitive local imports so shared-component changes stale an audit."""
    pending = list(target.rglob('*')) + [Path(p) for p in extra_files]
    hashes = {}
    while pending:
        path = pending.pop().resolve()
        if not path.is_file() or str(path) in hashes:
            continue
        hashes[str(path)] = file_hash(path)
        if path.suffix not in {'.ts', '.tsx', '.js', '.jsx', '.css'}:
            continue
        source = path.read_text(encoding='utf-8')
        if path.suffix == '.css':
            for asset in re.findall(r'''url\(["']?(/[^)"']+)["']?\)''', source):
                local_asset = (FRONTEND / 'public' / asset.lstrip('/')).resolve()
                if local_asset.is_relative_to((FRONTEND / 'public').resolve()) and local_asset.is_file():
                    pending.append(local_asset)
        for module in re.findall(r'''(?:from\s*|import\s*)["']([^"']+)["']''', source):
            if module.startswith('@/'):
                base = FRONTEND / 'src' / module[2:]
            elif module.startswith('.'):
                base = path.parent / module
            else:
                continue
            for candidate in [base, *[Path(str(base) + ext) for ext in ('.tsx', '.ts', '.css', '.json')], base / 'index.ts', base / 'index.tsx']:
                if candidate.is_file():
                    pending.append(candidate)
                    break
    return hashes


INSPECT = r"""() => {
  const root = document.querySelector('[data-dan-artifact]') || document.querySelector('main');
  if (!root) return {errors: ['No artifact root'], text: '', images: [], elements: []};
  const visible = e => { const s = getComputedStyle(e); const r = e.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) > 0 && r.width > 0 && r.height > 0; };
  const errors = [], seen = new Set(), elements = [], images = [];
  for (const e of root.querySelectorAll('[data-edit-id]')) {
    const id = e.dataset.editId;
    if (!id || id.startsWith('auto:') || seen.has(id)) errors.push(`Missing/duplicate/unstable edit ID: ${id}`);
    seen.add(id);
    if (visible(e)) elements.push({id, tag: e.tagName, text: e.innerText || ''});
  }
  const chunks = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n = walker.currentNode, e = n.parentElement;
    if (!e || e.closest('script,style,noscript,svg,option') || !n.textContent.trim() || !visible(e)) continue;
    chunks.push(n.textContent);
    const owner = e.closest('[data-edit-id]');
    if (!owner || !['H1','H2','H3','H4','H5','H6','P','SPAN','A','BUTTON','LABEL','LI','TD','TH','STRONG','EM','SMALL','SUMMARY','DT','DD','FIGCAPTION'].includes(owner.tagName)) {
      errors.push(`Visible copy has no editable text owner: ${n.textContent.trim().slice(0,80)}`);
    }
  }
  for (const img of root.querySelectorAll('img')) {
    if (!visible(img)) continue;
    images.push({src: img.currentSrc || img.src, id: img.dataset.editId || null});
    if (!img.complete || !img.naturalWidth) errors.push(`Image failed to load: ${img.src}`);
    if (!img.dataset.editId) errors.push(`Image has no edit ID: ${img.src}`);
  }
  if (!chunks.length) errors.push('No visible native copy (empty or raster-only page)');
  if (document.documentElement.scrollWidth > innerWidth + 1) errors.push('Horizontal overflow');
  return {errors, text: chunks.join(''), images, elements};
}"""


def audit(slug: str, origin: str, report_dir: Path) -> dict:
    from urllib.parse import unquote, urlparse
    from playwright.sync_api import sync_playwright

    target = artifact_dir(slug)
    spec = json.loads((target / 'editable-artifact.json').read_text(encoding='utf-8'))
    expected = spec.get('requiredText')
    if not isinstance(expected, list) or not expected or any(not isinstance(t, str) or not t.strip() for t in expected):
        raise ValueError('requiredText must list the actual visible copy, including headings, CTA and table labels')
    references = []
    for value in spec.get('references', []):
        path = (ROOT / value).resolve()
        if not path.is_file():
            raise ValueError(f'Reference does not exist: {path}')
        references.append(str(path))
    report_dir.mkdir(parents=True, exist_ok=True)
    views = []
    assets = set(references)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for width in (390, 560, 1280):
                page = browser.new_page(viewport={'width': width, 'height': 900})
                page_errors = []
                page.on('pageerror', lambda error: page_errors.append(str(error)))
                # Audit is read-only. Prevent analytics or accidental form writes.
                page.route('**/api/**', lambda route: route.fulfill(json=[]))
                page.goto(f'{origin.rstrip("/")}/preview/{slug}', wait_until='domcontentloaded', timeout=60000)
                page.evaluate('document.fonts.ready')
                page.locator('[data-dan-artifact],main').first.wait_for(timeout=15000)
                page.evaluate('''async () => Promise.all(Array.from(document.images, img => {
                  img.loading = 'eager'; return Promise.race([
                    img.decode().catch(() => {}), new Promise(resolve => setTimeout(resolve, 10000))
                  ]);
                }))''')
                result = page.evaluate(INSPECT)
                result['errors'].extend(page_errors)
                native = re.sub(r'\s+', '', result['text'])
                result['missingCopy'] = [s for s in expected if re.sub(r'\s+', '', s) not in native]
                result['width'] = width
                page.screenshot(path=str(report_dir / f'{width}.png'), full_page=True)
                for image in result['images']:
                    url = urlparse(image['src'])
                    local = (FRONTEND / 'public' / unquote(url.path).lstrip('/')).resolve()
                    if local.is_relative_to((FRONTEND / 'public').resolve()) and local.is_file():
                        assets.add(str(local))
                views.append(result)
                page.close()
        finally:
            browser.close()
    # The generated root must consume releases; IDs alone only enable preview patches.
    page_source = (target / 'page.tsx').read_text(encoding='utf-8')
    release_wired = all(token in page_source for token in ('EditableProvider', 'release.gen.json', 'toEditableOverrides'))
    report = {'slug': slug, 'structuralPass': release_wired and all(not v['errors'] and not v['missingCopy'] for v in views),
              'releaseWired': release_wired, 'visualReview': 'pending', 'references': references,
              'views': views, 'extraFiles': sorted(assets), 'fingerprint': source_fingerprint(target, sorted(assets)),
              'createdAt': datetime.now(timezone.utc).isoformat()}
    write_json(report_dir / 'audit.json', report)
    return report


def finish(slug: str, report_dir: Path, notes: str, register: bool) -> dict:
    report = json.loads((report_dir / 'audit.json').read_text(encoding='utf-8'))
    if report.get('slug') != slug or not report.get('structuralPass'):
        raise ValueError('Run a passing audit for this slug before finishing')
    if report['fingerprint'] != source_fingerprint(artifact_dir(slug), report['extraFiles']):
        raise ValueError('Source/assets changed after audit; rerun audit and inspect the new screenshots')
    if not notes.strip():
        raise ValueError('Describe the visual comparison, remaining differences, and edit verification')
    result = {'slug': slug, 'structuralPass': True, 'visualReview': notes,
              'previewUrl': f'/preview/{slug}', 'registration': 'not requested'}
    if register:
        room = os.environ.get('DAN_ROOM_ID') or os.environ.get('DAN_SESSION_ID')
        project = os.environ.get('DAN_PROJECT_ID')
        if not room or not project:
            raise ValueError('Registration requires the current chat DAN_ROOM_ID and DAN_PROJECT_ID')
        sys.path.insert(0, str(ROOT))
        from app.services.chat_artifact_registration import request_registration_via_core
        reply = request_registration_via_core([str(artifact_dir(slug) / 'page.tsx')], room, project)
        if reply is None:
            raise RuntimeError('Core registration was not confirmed; do not claim the artifact is registered')
        result['registration'] = reply
    write_json(report_dir / 'finished.json', result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'audit', 'finish'])
    parser.add_argument('--slug', required=True)
    parser.add_argument('--title', default='制作中')
    parser.add_argument('--origin', default='http://localhost:3001')
    parser.add_argument('--report-dir', type=Path)
    parser.add_argument('--review-notes', default='')
    parser.add_argument('--register', action='store_true')
    args = parser.parse_args()
    try:
        artifact_dir(args.slug)  # validate before deriving any paths
        report_dir = args.report_dir or ROOT / 'scratch/editable-artifacts' / args.slug
        if args.action == 'init':
            result = scaffold(args.slug, args.title)
        elif args.action == 'audit':
            report = audit(args.slug, args.origin, report_dir)
            result = {k: report[k] for k in ('slug', 'structuralPass', 'releaseWired', 'visualReview')}
            result['report'] = str(report_dir / 'audit.json')
            result['issues'] = [{'width': v['width'], 'errors': v['errors'], 'missingCopy': v['missingCopy']} for v in report['views']]
        else:
            result = finish(args.slug, report_dir, args.review_notes, args.register)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('structuralPass', True) else 1
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
