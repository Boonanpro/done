"""Import source-declared CC0 assets; do not equate a catalog import with QA.

Refresh is explicit. All network reads have finite timeouts and no retry loop.
The editor's reference list is not flooded with 3D assets.
"""
import argparse
import collections
import datetime
import hashlib
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.enrich_production_library import read, save

OUT = ROOT / 'docs/reference-index/production-assets.json'
CACHE = ROOT / 'scratch/production-library-enrichment/sources/polyhaven-assets.json'
KINDS = {0: 'lighting_environment', 1: 'material', 2: 'model_3d'}


def normalize(ident, raw):
    return {'id': 'polyhaven-' + ident, 'provider': 'Poly Haven', 'provider_id': ident,
            'kind': KINDS[raw['type']], 'title': raw['name'], 'source_url': 'https://polyhaven.com/a/' + ident,
            'description': raw.get('description', ''), 'tags': raw.get('tags', []),
            'categories': raw.get('categories', []), 'attributes': raw.get('attributes', {}),
            'preview_url': raw.get('thumbnail_url'), 'authors': raw.get('authors', {}),
            'license': 'CC0', 'license_source': 'https://polyhaven.com/license',
            'metadata_basis': 'publisher_declared', 'quality_status': 'unreviewed',
            'compatibility': 'Requires a compatible 3D renderer; not a native Dan timeline clip.',
            'files_endpoint': 'https://api.polyhaven.com/files/' + ident,
            'max_resolution': raw.get('max_resolution'), 'files_hash': raw.get('files_hash')}


def main(args):
    with httpx.Client(timeout=30, follow_redirects=True,
                      headers={'User-Agent': 'DanProductionLibrary/1.0'}) as client:
        if args.refresh or not CACHE.exists():
            response = client.get('https://api.polyhaven.com/assets')
            response.raise_for_status()
            save(CACHE, response.json())
        raw = read(CACHE)
        old = {r['id']: r for r in read(OUT, {}).get('assets', [])}
        rows = []
        for ident, value in raw.items():
            if value.get('type') not in KINDS:
                continue
            row = normalize(ident, value)
            previous = old.get(row['id'], {})
            # Never carry a quality approval across a provider content revision.
            if previous.get('files_hash') == row['files_hash']:
                for field in ('quality_status', 'quality_review', 'local_preview', 'preview_sha256', 'files'):
                    if field in previous: row[field] = previous[field]
            rows.append(row)
        if args.samples:
            for kind in KINDS.values():
                sample = sorted((r for r in rows if r['kind'] == kind),
                                key=lambda r: -(raw[r['provider_id']].get('download_count') or 0))[:args.samples]
                for row in sample:
                    response = client.get(row['files_endpoint'])
                    response.raise_for_status()
                    save(ROOT / 'app/data/production-assets' / (row['id'] + '-files.json'), response.json())
                    if not row.get('preview_url'): continue
                    response = client.get(row['preview_url'])
                    response.raise_for_status()
                    from PIL import Image
                    import io
                    im = Image.open(io.BytesIO(response.content))
                    im.verify()
                    path = ROOT / 'uploads/reference-library' / (row['id'] + '.png')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    # Normalize the extension to actual PNG data.
                    Image.open(io.BytesIO(response.content)).convert('RGB').save(path)
                    row['local_preview'] = path.relative_to(ROOT).as_posix()
                    row['preview_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
                    print(json.dumps({'sample': row['id'], 'kind': kind, 'preview_decoded': True}), flush=True)
        save(OUT, {'schema_version': 1, 'source': 'https://api.polyhaven.com/assets',
                   'retrieved_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'assets': rows})
        print(json.dumps({'assets': len(rows), 'kinds': dict(collections.Counter(r['kind'] for r in rows)),
                          'local_previews': sum('local_preview' in r for r in rows),
                          'quality_approved': sum(r['quality_status'] == 'approved' for r in rows)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--samples', type=int, default=0, choices=range(0, 11))
    main(parser.parse_args())
