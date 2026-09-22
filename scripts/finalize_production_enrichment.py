"""Merge validated records while honoring both old and new disputed audits."""
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.enrich_production_library import OUT, OBS, INDEX, VERSION, read, save, validate


def main():
    rows = {r['id']: r for r in read(INDEX)['references']}
    baseline = read(OUT / 'observations-before.json', {})
    current = read(OBS, {})
    old = read(ROOT / 'scratch/discovery-observations/audit-results.json', [])
    disputed = {'yt-' + r['id'] for r in old if r.get('audit', {}).get('supported') is False}
    accepted, held = {}, {}
    for path in sorted((OUT / 'records').glob('*.json')):
        record = read(path)
        ident = record['id']
        if ident not in rows: continue
        value = record.get('analysis')
        audit = read(OUT / 'audits' / (ident + '.json'), {})
        issue = None
        if not validate(value, rows[ident].get('duration_seconds')):
            issue = 'invalid_or_inaccessible_analysis'
        elif audit.get('audit', {}).get('supported') is False:
            issue = 'second_view_disagrees'
        elif ident in disputed and not (audit.get('fingerprint') == record.get('fingerprint')
                                        and audit.get('audit', {}).get('supported') is True):
            issue = 'prior_dispute_requires_new_audit'
        if issue:
            held[ident] = issue
            # Undo only this run's own observation, never another writer's data.
            if current.get(ident, {}).get('observed_at') == record.get('observed_at') and record.get('observed_at'):
                if ident in baseline: current[ident] = baseline[ident]
                else: current.pop(ident, None)
            continue
        accepted[ident] = {**value, 'source_url': record['source_url'],
                           'basis': 'model_video_observation', 'analysis_version': VERSION,
                           'quality_status': 'model_review_only', 'observed_at': record['observed_at']}
    current.update(accepted)
    save(OBS, current)
    report = {'analyzed': len(accepted) + len(held), 'accepted': len(accepted), 'held': held,
              'observed_before': len(baseline), 'observed_after': len(current),
              'new_observed_works': len(set(current) - set(baseline)),
              'upgraded_existing_works': len(set(accepted) & set(baseline)),
              'genres': dict(collections.Counter(rows[k]['labels']['primary_genre'] for k in accepted)),
              'segments': sum(len(v['observations']) for v in accepted.values()),
              'facets': sum(sum(len(e) for e in v['facets'].values()) for v in accepted.values()),
              'techniques': sum(len(v['techniques']) for v in accepted.values()),
              'audits': read(OUT / 'audit-report.json', {}).get('sample_size', 0)}
    save(OUT / 'final-report.json', report)
    print(report)


if __name__ == '__main__': main()
