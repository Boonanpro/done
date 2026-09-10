"""Shared operation arguments for conversational and background editing."""
import json

def resolve_results(value, results):
    """Resolve typed references without interpolation or evaluating model code."""
    if isinstance(value, dict):
        if '$result' in value:
            index = value['$result']
            if set(value) != {'$result', 'path'} or type(index) is not int or not 0 <= index < len(results):
                raise ValueError('Batch references must point to an earlier operation with $result and path')
            path = value['path']
            if not isinstance(path, str) or not path:
                raise ValueError('Batch reference path must be nonempty')
            current = results[index]
            try:
                for key in path.split('.'):
                    if isinstance(current, list):
                        if not key.isdigit():
                            raise KeyError(key)
                        current = current[int(key)]
                    elif isinstance(current, dict):
                        current = current[key]
                    else:
                        raise KeyError(key)
            except (KeyError, IndexError):
                raise ValueError(f'Batch result {index} has no path {path}') from None
            return json.loads(json.dumps(current))
        return {k: resolve_results(v, results) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_results(v, results) for v in value]
    return value


from app.services import timeline_commands as tc

def split_at_times(seq, clip_id, times):
    if not isinstance(times, list):
        return tc.split_clip(seq, clip_id=clip_id, at=float(times))
    original = json.loads(json.dumps(seq))
    results = []
    try:
        for at in sorted(set(float(t) for t in times), reverse=True):
            result = tc.split_clip(seq, clip_id=clip_id, at=at)
            if not result.get('ok'):
                seq.clear(); seq.update(original)
                return {**result, 'rolled_back': True}
            results.append(result)
    except Exception:
        seq.clear(); seq.update(original)
        raise
    return {'ok': True, 'cuts': results}


def addition_spans(operations):
    """Explicit time spans of additive edits; never grants mutation of old clips."""
    import math
    spans=[]
    for op in operations:
        name=op.get('op');args=op.get('args') or {}
        if name not in {'add_clip','add_caption','add_region','add_audio','add_overlay','insert_freeze'}:continue
        try:
            start=float(args.get('at',0) if name=='add_audio' else args['timeline_start'])
            end=float(args['timeline_end']) if 'timeline_end' in args else start+float(args['duration'])
        except (TypeError,ValueError,KeyError):continue
        if math.isfinite(start) and math.isfinite(end) and 0<=start<end:spans.append([start,end])
    return spans
