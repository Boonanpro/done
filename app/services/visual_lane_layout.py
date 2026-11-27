"""Place pictures and captions on reusable display lanes, preserving compositing order."""
import math

from app.services.lane_switches import clip_lanes, lane_key


def _items(seq):
    tracks = seq.get('tracks', [])
    lanes = clip_lanes(tracks)
    return [(lanes[str(c['id'])][1], c, t) for t in tracks if t.get('type') != 'audio'
            for c in t.get('clips', []) if c.get('id')]


def _overlaps(c, start, end):
    return c['timeline_start'] < end - .0001 and start < c['timeline_end'] - .0001


def _floor(clip, track):
    return 2 if clip.get('track') == 'caption' or track.get('type') == 'caption' else 1


def assign_added(seq, clip_id, *, front):
    items = _items(seq)
    layer, clip, track = next(row for row in items if row[1]['id'] == clip_id)
    a, b = clip['timeline_start'], clip['timeline_end']
    simultaneous = [(z, c) for z, c, _ in items if c is not clip and _overlaps(c, a, b)]
    # Keep an automatically placed picture below existing captions if the allocator
    # chose that order. An explicit foreground request must clear every active item.
    behind = [z for z, _ in simultaneous if front or z <= layer]
    minimum = max(_floor(clip, track), math.floor(max(behind, default=-1)) + 1)
    above = [z for z, _ in simultaneous if not front and z > layer]
    if above and minimum >= min(above):
        return
    while seq.get('lane_switches', {}).get(lane_key('visual', minimum), {}).get('hidden'):
        minimum += 1
        if above and minimum >= min(above):
            return
    clip['layer'] = minimum


def compact(seq):
    """Change display lane numbers only. Keep the stack at every shared frame."""
    rows = sorted(_items(seq), key=lambda row: row[0])
    placed = []
    changes = []
    switches = seq.get('lane_switches', {})
    fixed = {z for z, c, t in rows if c.get('approved') or c.get('locked') or t.get('locked') or t.get('hidden')}
    fixed |= {z for z, _, _ in rows if switches.get(lane_key('visual', z))}
    for original, c, t in rows:
        a, b = c['timeline_start'], c['timeline_end']
        if original == 0 or original in fixed:
            chosen = original
        else:
            below = [z for z, start, end in placed if start < b - .0001 and a < end - .0001]
            chosen = max(_floor(c, t), math.floor(max(below, default=-1)) + 1)
            while chosen in fixed or switches.get(lane_key('visual', chosen)):
                chosen += 1
            # Only move downward. In particular, preserve intentional fractional
            # layers and the legacy tie order of overlapping clips on one layer.
            chosen = min(original, chosen)
        if chosen != original:
            changes.append((c, chosen))
        placed.append((chosen, a, b))
    for clip, layer in changes:
        clip['layer'] = layer
    return {'ok': True, 'moved': len(changes), 'layers': len({row[0] for row in placed})}
