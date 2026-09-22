"""Publish only structurally valid, undisputed observations, preserving raw evidence."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.inspect_discovery_references import valid_observation

def main():
 out=ROOT/'scratch/discovery-observations'
 target=ROOT/'docs/reference-index/visual-observations.json'
 catalog=json.loads((ROOT/'docs/reference-index/videos.json').read_text(encoding='utf8'))['references']
 audits=json.loads((out/'audit-results.json').read_text(encoding='utf8'))
 disputed={r['id'] for r in audits if r.get('audit',{}).get('supported') is not True}
 published=json.loads(target.read_text(encoding='utf8'));rejected={}
 for row in catalog:
  ident=row['video_id'];path=out/(ident+'.json')
  if not path.exists():continue
  value=json.loads(path.read_text(encoding='utf8'))
  if ident in disputed or not valid_observation(value,row.get('duration_seconds')):
   published.pop(row['id'],None)
   rejected[ident]='audit_disagreement' if ident in disputed else 'invalid_observation_or_time_range'
  else:published[row['id']]=value
 temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(published,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(target)
 genres={}
 for row in catalog:
  if row['id'] in published:
   genre=row['labels']['primary_genre'];genres[genre]=genres.get(genre,0)+1
 report={'published':len(published),'segments':sum(len(r.get('observations',[])) for r in published.values()),
         'genres':genres,'rejected':rejected,'audit_sample_size':len(audits),
         'limitations':['Model observations, not human-verified footage or production-method proof.',
                        'Only five records independently rechecked; passing schema is not proof of accuracy.']}
 (out/'quality-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps(report,ensure_ascii=True))
if __name__=='__main__':main()
