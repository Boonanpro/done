"""Save the experimental URL index and corrected analysis, not a live deployment."""
import copy,datetime,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'scratch/reference-url-pilot';DEST=ROOT/'docs/reference-index'

def main():
 DEST.mkdir(parents=True,exist_ok=True)
 rows=json.loads((SRC/'labeled-all.json').read_text(encoding='utf8'))
 assert len(rows)==len({r['id'] for r in rows})==1178
 normalized=[]
 for row in rows:
  normalized.append({
   'id':'yt-'+row['id'],'video_id':row['id'],'url':'https://www.youtube.com/watch?v='+row['id'],
   'title':row['title'],'publisher':row.get('channel'),'publisher_id':row.get('channel_id'),
   'duration_seconds':row.get('duration'),'views_at_discovery':row.get('view_count'),
   'retrieved_at':row['retrieved_at'],'description_excerpt':row.get('description') or '',
   'thumbnail_url':row.get('thumbnails',[{}])[-1].get('url') if row.get('thumbnails') else None,
   'labels':{'primary_genre':row['genre'],'genre_probabilities':row['genre_probabilities'],'medium':row['medium'],'taste':[]},
   'label_basis':'publisher_search_metadata','visual_inspection':'not_performed',
   'reference_uses':row['reference_uses'],'availability':'found_in_youtube_search','embed_status':'unchecked',
   'discovery':{'groups':row['discovery_groups'],'queries':row['discovery_queries']},
  })
 analysis=json.loads((SRC/'deep/analysis.json').read_text(encoding='utf8'))
 audit=json.loads((SRC/'deep/audit.json').read_text(encoding='utf8'))
 raw=copy.deepcopy(analysis)
 for correction in audit['corrections']:
  matches=[s for s in analysis['segments'] if s['start']==correction['segment_start']]
  assert len(matches)==1
  matches[0].update(correction['corrected_fields'])
  matches[0]['audit_correction']=correction['issue']
 for n,seg in enumerate(analysis['segments']):
  assert 0<=seg['start']<seg['end']<=163
  if n:assert abs(analysis['segments'][n-1]['end']-seg['start'])<.001
  seg.update(id=f'yt-1QNsdr-Qx_I-segment-{n+1:02}',timestamp_precision='approximate_seconds',
   source_url='https://www.youtube.com/watch?v=1QNsdr-Qx_I&t='+str(int(seg['start']))+'s',
   implementation_evidence='inferred',observation_basis='gemini_agentic_video',
   reproduction_note='Proposed method, not evidence of the original production pipeline.')
 target=next(r for r in normalized if r['video_id']=='1QNsdr-Qx_I')
 analysis['title']=target['title']
 analysis.update(reference_id=target['id'],source_url=target['url'],
  model='gemini-3.8-flash',processing='agentic',audit=audit,
  reviewed_stills={'method':'local contact sheet and closing frame visual inspection','timestamps_approx':[7.5,22.5,37.5,52.5,67.5,82.5,97.5,112.5,127.5,142.5,157.5,158]},
  caveats=['29 semantic intervals, not an exhaustive frame-accurate shot list.',
           'Independent model reinspection found and corrected four issues; it is not proof that all observations are correct.',
           'Audio observations are model-reviewed. No claim of manual listening to every second.',
           'Source identity comes from publisher metadata; visual analysis does not establish product-release facts.'])
 target.update(visual_inspection='agentic_analysis_with_audit_and_sampled_stills',analysis_file='openai-gpt6-astra.json')
 target['labels']['taste']=analysis['overall_style']
 target['label_basis']='publisher_metadata_and_agentic_video_analysis'
 target['labels']['medium']='mixed'
 (DEST/'openai-gpt6-astra.json').write_text(json.dumps(analysis,ensure_ascii=False,indent=2),encoding='utf8')
 previous_path=DEST/'videos.json'
 previous=json.loads(previous_path.read_text(encoding='utf8')) if previous_path.exists() else {}
 by_id={r['id']:r for r in previous.get('references',[])}
 for row in normalized:
  old=by_id.get(row['id'],{})
  for key in ('embed_status','embed_evidence'):
   if key in old:row[key]=old[key]
 manifest={'schema_version':1,'status':previous.get('status','experimental_not_connected_to_live_editor'),'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'count':len(normalized),'method':'60 queries across 20 discovery groups; all unique results retained. Metadata-based labels are provisional, not aesthetic quality ratings.',
  'references':normalized}
 (DEST/'videos.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps({'references':len(normalized),'detailed_segments':len(analysis['segments']),'corrections':len(audit['corrections'])}))

if __name__=='__main__':main()
