"""Enforce edit boundaries independently of the model's instructions."""
from __future__ import annotations

import copy


def lanes(sequence):
    # Older timelines contain multiple lanes without IDs. Do not collapse all
    # of them into the same 'None' key when checking settings and order.
    return [(str(t['id']) if t.get('id') else f'__legacy_lane_{i}', t)
            for i, t in enumerate(sequence.get('tracks', []))]


def clips(sequence):
    return {str(c['id']): (lane, c)
            for lane, t in lanes(sequence) for c in t.get('clips', [])}


def make_scope(sequence, selected):
    indexed = clips(sequence)
    ids = {str(c.get('id') if isinstance(c, dict) else c) for c in selected}
    ids &= indexed.keys()
    links = {indexed[c][1].get('link_id') for c in ids} - {None, ''}
    ids |= {cid for cid, (_, c) in indexed.items() if c.get('link_id') in links}
    spans = [[indexed[c][1]['timeline_start'], indexed[c][1]['timeline_end']] for c in ids]
    return {'clip_ids': sorted(ids), 'spans': spans}


def violations(before, after, scope=None):
    old, new = clips(before), clips(after)
    allowed = set(scope['clip_ids']) if scope is not None else set(old)
    locked_tracks = {lane for lane, t in lanes(before) if t.get('locked')}
    protected = {cid for cid, (lane, c) in old.items()
                 if lane in locked_tracks or c.get('locked') or c.get('approved')}
    errors = []
    for cid, entry in old.items():
        if (cid not in allowed or cid in protected) and new.get(cid) != entry:
            errors.append(f'変更対象外または承認済みのクリップです: {cid}')
    # Track settings and compositing order affect clips even if their JSON is identical.
    old_tracks = {lane: {k: v for k, v in t.items() if k != 'clips'} for lane, t in lanes(before)}
    new_tracks = {lane: {k: v for k, v in t.items() if k != 'clips'} for lane, t in lanes(after)}
    protected_lanes = {old[cid][0] for cid in protected}
    if any(old_tracks[tid] != new_tracks.get(tid) for tid in protected_lanes):
        errors.append('承認済みクリップのレーン設定を変更できません')
    protected_spans = [(old[cid][1]['timeline_start'], old[cid][1]['timeline_end']) for cid in protected]
    for cid, entry in new.items():
        if entry != old.get(cid):
            c = entry[1]
            if any(float(c['timeline_start']) < b and float(c['timeline_end']) > a for a, b in protected_spans):
                errors.append(f'承認済みの時間範囲に変更が重なっています: {cid}')
    if scope is None and not protected:
        return errors
    if scope is None:
        # A global format/order change would also change the approved shot's pixels.
        for key in set(before) | set(after):
            if key not in {'tracks', 'duration'} and before.get(key) != after.get(key):
                errors.append(f'承認済みの映像に影響する全体設定は変更できません: {key}')
        if [lane for lane, _ in lanes(after) if lane in old_tracks] != list(old_tracks):
            errors.append('承認済みの映像があるため既存レーンの重ね順は変更できません')
        return errors
    if any(new_tracks.get(tid) != meta for tid, meta in old_tracks.items()):
        errors.append('部分修正では既存レーンの設定を変更できません')
    if [lane for lane, _ in lanes(after) if lane in old_tracks] != list(old_tracks):
        errors.append('部分修正では既存レーンの重ね順を変更できません')
    for key in set(before) | set(after):
        if key not in {'tracks', 'duration'} and before.get(key) != after.get(key):
            errors.append(f'部分修正では作品全体の設定を変更できません: {key}')
    for cid in new.keys() - old.keys():
        c = new[cid][1]
        if not any(float(a) - 0.001 <= float(c.get('timeline_start', -1))
                   and float(c.get('timeline_end', 1e20)) <= float(b) + 0.001
                   for a, b in scope['spans']):
            errors.append(f'追加クリップが対象の時間範囲外です: {cid}')
    return errors


def attach(draft, selected):
    draft['edit_scope'] = make_scope(draft['sequence'], selected)
    draft['base_sequence'] = copy.deepcopy(draft['sequence'])
