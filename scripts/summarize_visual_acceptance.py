"""Report both time to a visible comparison and time to its final refinement."""
import json,math,sys
from pathlib import Path
from summarize_visual_audio_trial import summarize

folder=Path(sys.argv[1])
expectations=json.loads((folder/'expectations.json').read_text(encoding='utf8'))
cases=[];times=[];final_times=[]
for name,_,target in expectations:
    data=json.loads((folder/name/'final.json').read_text(encoding='utf8'))
    result=summarize(folder/name)
    (folder/name/'measurement.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    required=result['rows'][:3]
    measured=[r['display_wait_ms'] for r in required]
    if any(t is None for t in measured):raise RuntimeError(f'{name}: missing required visual; do not exclude it from latency statistics')
    times.extend(measured)
    final_times.extend(r['last_update_after_speech_end_ms'] for r in required)
    cases.append({'case':name,'final_target_selected':any(i.get('library_id')==target for i in data['presentations'][-1]['items']),
        'first_display_ms':measured,'last_update_ms':[r['last_update_after_speech_end_ms'] for r in required],
        'spoken_reports':[r['spoken_reports'] for r in required],
        'backend_starts':sum(r['backend_started'] for r in result['rows']),
        'browser_errors':result['browser_errors'],'video':str((folder/name/'conversation.mp4').resolve())})
times.sort()
final_times.sort()
result={'cases':cases,'visual_turns':len(times),'median_display_ms':times[math.ceil(len(times)*.5)-1],
    'p90_display_ms':times[math.ceil(len(times)*.9)-1],
    'median_final_update_ms':final_times[math.ceil(len(final_times)*.5)-1],
    'p90_final_update_ms':final_times[math.ceil(len(final_times)*.9)-1],
    'scope':'Prepared library comparisons, including rendering. First usable display and last refinement are separate; delayed transcription can refine a visible comparison later. Reused visuals are already on screen. Requires manual relevance and speech review; not a general success-rate estimate.'}
result['passed']=result['median_display_ms']<=1000 and result['p90_display_ms']<=2000 and all(c['final_target_selected'] and all(c['spoken_reports']) and not c['backend_starts'] and not c['browser_errors'] for c in cases)
(folder/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,ensure_ascii=False))
if not result['passed']:raise SystemExit(1)
