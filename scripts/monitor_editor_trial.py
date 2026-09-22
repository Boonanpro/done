"""Read-only editor trial monitor. Never connects, speaks, reloads or edits a room.

Use --room ROOM --follow while a user talks. Reports retain original transcripts,
explicit input/decision/turn IDs, observed displays and failures. Missing evidence
stays missing; silence is never treated as completed work.
"""
import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def milliseconds(value):
    if isinstance(value,(int,float)):return value
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()*1000
    except (TypeError,ValueError,AttributeError):return None


def read_events(paths):
    events=[];errors=[]
    for path in paths:
        raw=path.read_text(encoding='utf8');lines=raw.splitlines()
        for number,line in enumerate(lines,1):
            try:
                event=json.loads(line)
                if not isinstance(event,dict):raise ValueError('not an object')
            except ValueError:
                # The writer may be midway through its final line.
                if number==len(lines) and not raw.endswith('\n'):continue
                errors.append({'file':str(path),'line':number});continue
            event={**event,'room_id':event.get('room_id') or path.parents[2].name,
                   'source_file':str(path),'source_line':number}
            events.append(event)
    events.sort(key=lambda e:(milliseconds(e.get('at')) or 0,e['source_file'],e['source_line']))
    return events,errors


def summarize(events,errors=()):
    inputs={};decisions={};turns={};dialogue={};unlinked=[];failures=[];connections=[];builds=[]
    def entry(event,ident):
        key=(event.get('room_id'),event.get('content_id'),ident)
        return inputs.setdefault(key,{'input_id':ident,'room_id':key[0],'content_id':key[1],
            'text':'','decisions':[],'displays':[],'selections':[],'backend_turns':[],'reports':[]})
    for e in events:
        kind=str(e.get('type') or '');ident=e.get('input_id')
        if kind in ('user_transcript','assistant_transcript'):
            message_id=e.get('item_id') or (e['source_file'],e['source_line'])
            dialogue[(e['source_file'],message_id)]={k:e.get(k) for k in ('at','type','text','item_id','content_id','room_id')}
            if kind=='user_transcript' and e.get('item_id'):
                row=entry(e,e['item_id']);row['text']=e.get('text','');row['transcript_end_ms']=e.get('end_ms')
        if kind in ('visual_decision_started','visual_decision') and ident:
            row=entry(e,ident)
            if e.get('input_text') and not row['text']:row['text']=e['input_text']
            if kind=='visual_decision_started':
                decision={'decision_id':e['decision_id'],'started_at':e.get('at'),'input_text':e.get('input_text')}
                row['decisions'].append(decision);decisions[e['decision_id']]=decision
            else:row['applied_decision']={k:e.get(k) for k in ('action','destination','selected_library_ids','elapsed_ms')}
        if kind in ('visual_decision_finished','visual_decision_failed'):
            decision=decisions.get(e.get('decision_id'))
            if decision is None:unlinked.append(e)
            else:
                decision.update({k:e.get(k) for k in ('action','available','selected_library_ids','elapsed_ms','verification','failure','message')})
                start=milliseconds(decision.get('started_at'));end=milliseconds(e.get('at'))
                decision['request_to_response_ms']=round(end-start) if start is not None and end is not None else None
        if kind in ('reference_library_displayed','reference_selected'):
            if not ident:unlinked.append(e)
            else:
                row=entry(e,ident)
                result={k:e.get(k) for k in ('at','presentation_id','item_id','selected_library_ids','count','ok','saved','ranking_ms','elapsed_ms','error')}
                if kind=='reference_library_displayed':
                    sound=e.get('input_sound_at_ms');at=milliseconds(e.get('at'))
                    result['last_detected_sound_to_display_ms']=round(at-sound) if at is not None and isinstance(sound,(int,float)) else None
                    row['displays'].append(result)
                else:row['selections'].append(result)
        if kind=='live_backend_started':
            if not ident or not e.get('turn_id'):unlinked.append(e)
            else:
                row=entry(e,ident);turns[(e['room_id'],e['turn_id'])]=row
                turn={k:e.get(k) for k in ('at','turn_id','model','backend','billing')}
                if re.fullmatch('[a-f0-9]{32}',e['turn_id']):
                    turn['record']=str(Path(e['source_file']).parent.parent/(e['turn_id']+'.json'))
                row['backend_turns'].append(turn)
        if kind in ('live_presentation_delivered','live_backend_message_delivered'):
            row=turns.get((e.get('room_id'),e.get('turn_id')))
            if row is not None:row['reports'].append({k:e.get(k) for k in ('at','type','turn_id','presentation_id','phase','message_id')})
        if kind in ('disconnected','connection_stage','live_session_closed','live_voice_paused'):
            connections.append({k:e.get(k) for k in ('at','type','stage','reason','content_id','room_id')})
        if e.get('client_build') or e.get('instructions_hash'):
            builds.append({k:e.get(k) for k in ('at','client_build','instructions_hash','model','content_id')})
        if 'error' in kind or kind.endswith('_failed') or e.get('available') is False:
            failures.append({k:e.get(k) for k in ('at','type','input_id','decision_id','turn_id','content_id','message','failure')})
    return {'event_count':len(events),'inputs':list(inputs.values()),'dialogue':list(dialogue.values()),
        'connections':connections,'builds':builds,'failures':failures,'unlinked_events':unlinked,'malformed_lines':list(errors),
        'measurement_note':'Last detected sound is an acoustic-meter observation, not a guaranteed sentence end. Transcript timestamps are model offsets. A displayed reference is not a completed video. Missing links are not inferred from timing.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--room',required=True)
    parser.add_argument('--follow',action='store_true')
    parser.add_argument('--seconds',type=float)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',args.room):parser.error('Invalid room ID')
    folder=ROOT/'uploads/production-assets'/args.room/'assistant/events'
    output=args.output or ROOT/'scratch/editor-monitor'/args.room/'summary.json'
    deadline=time.monotonic()+args.seconds if args.seconds is not None else None
    fingerprint=None
    while True:
        paths=sorted(folder.glob('*.jsonl'))
        current=tuple((str(p),p.stat().st_mtime_ns,p.stat().st_size) for p in paths)
        if current!=fingerprint:
            events,errors=read_events(paths);report=summarize(events,errors)
            output.parent.mkdir(parents=True,exist_ok=True)
            tmp=output.with_suffix('.tmp');tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(output)
            print(json.dumps({'room':args.room,'events':report['event_count'],'inputs':len(report['inputs']),
                'failures':len(report['failures']),'unlinked':len(report['unlinked_events']),'report':str(output)},ensure_ascii=False),flush=True)
            fingerprint=current
        if not args.follow or (deadline is not None and time.monotonic()>=deadline):break
        time.sleep(min(2,max(0,deadline-time.monotonic())) if deadline is not None else 2)


if __name__=='__main__':main()
