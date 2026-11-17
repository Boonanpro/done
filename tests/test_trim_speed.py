"""trim_clip on clips whose speed is not 1 (2026-11-18: 中村さんLINE特典の speed 0.702 の実写と
1.08 の顔の段で、trimが素材の長さ＝タイムラインの長さで計算して検証に落ち、壊れた形が下書きに残った)."""
import copy
import json

import pytest

import app.timeline_mcp_server as m
from app.services import timeline_commands as tc
from app.services import timeline_draft as td

ASSETS = {'v1': {'id': 'v1', 'kind': 'video', 'filename': 'a.mp4', 'metadata': {'duration': 100.0}}}


def _seq():
    return {'duration': 30, 'format': '16:9', 'frame_rate': 30, 'tracks': [
        {'id': 'v', 'type': 'video', 'clips': [
            # 1.08x: 10s of timeline plays 10.8s of source
            {'id': 'fast', 'asset_id': 'v1', 'link_id': 'L', 'speed': 1.08,
             'timeline_start': 0.0, 'timeline_end': 10.0, 'source_start': 20.0, 'source_end': 30.8},
            # 0.702x slow motion b-roll
            {'id': 'slow', 'asset_id': 'v1', 'speed': 0.702,
             'timeline_start': 12.0, 'timeline_end': 22.0, 'source_start': 1.0, 'source_end': 8.02}]},
        {'id': 'a', 'type': 'audio', 'clips': [
            {'id': 'fast_a', 'asset_id': 'v1', 'link_id': 'L', 'speed': 1.08,
             'timeline_start': 0.0, 'timeline_end': 10.0, 'source_start': 20.0, 'source_end': 30.8}]}]}


def _clip(seq, cid):
    return next(c for t in seq['tracks'] for c in t['clips'] if c['id'] == cid)


def _consistent(seq, cid):
    c = _clip(seq, cid)
    t = c['timeline_end'] - c['timeline_start']
    s = c['source_end'] - c['source_start']
    assert abs(t - s / c['speed']) < 0.01, (cid, t, s, c['speed'])


@pytest.mark.parametrize('cid,edge,new_time,exp_tl,exp_src', [
    # right edge shorten / extend: source moves by timeline change x speed
    ('fast', 'right', 8.0, (0.0, 8.0), (20.0, 28.64)),
    ('fast', 'right', 11.0, (0.0, 11.0), (20.0, 31.88)),
    ('slow', 'right', 20.0, (12.0, 20.0), (1.0, 6.616)),
    ('slow', 'right', 23.0, (12.0, 23.0), (1.0, 8.722)),
    # left edge shorten / extend
    ('fast', 'left', 2.0, (2.0, 10.0), (22.16, 30.8)),
    ('slow', 'left', 14.0, (14.0, 22.0), (2.404, 8.02)),
    ('slow', 'left', 11.0, (11.0, 22.0), (0.298, 8.02)),
])
def test_trim_scales_source_by_speed(cid, edge, new_time, exp_tl, exp_src):
    seq = _seq()
    assert tc.trim_clip(seq, ASSETS, clip_id=cid, edge=edge, new_time=new_time)['ok']
    c = _clip(seq, cid)
    assert (c['timeline_start'], c['timeline_end']) == pytest.approx(exp_tl, abs=1e-3)
    assert (c['source_start'], c['source_end']) == pytest.approx(exp_src, abs=2e-3)
    _consistent(seq, cid)
    if cid == 'fast':   # the linked audio twin moves the same way
        a = _clip(seq, 'fast_a')
        assert (a['timeline_start'], a['timeline_end'], a['source_start'], a['source_end']) == \
            (c['timeline_start'], c['timeline_end'], c['source_start'], c['source_end'])
    assert not [p for p in tc.validate_sequence(seq, ASSETS) if 'span' in p or 'sync' in p]


def test_left_extend_stops_at_source_zero():
    seq = _seq()
    assert tc.trim_clip(seq, ASSETS, clip_id='slow', edge='left', new_time=0.0)['ok']
    c = _clip(seq, 'slow')
    assert c['source_start'] == 0.0
    assert c['timeline_start'] == pytest.approx(22.0 - 8.02 / 0.702, abs=2e-3)
    _consistent(seq, 'slow')


def test_right_extend_stops_at_asset_end():
    seq = _seq()
    assert tc.trim_clip(seq, ASSETS, clip_id='fast', edge='right', new_time=200.0)['ok']
    c = _clip(seq, 'fast')
    assert c['source_end'] == 100.0
    assert c['timeline_end'] == pytest.approx((100.0 - 20.0) / 1.08, abs=2e-3)
    _consistent(seq, 'fast')


def test_speed_one_unchanged():
    seq = _seq()
    c = _clip(seq, 'slow'); c['speed'] = 1.0; c['source_end'] = 11.0
    assert tc.trim_clip(seq, ASSETS, clip_id='slow', edge='right', new_time=20.0)['ok']
    assert (c['source_start'], c['source_end']) == (1.0, 9.0)
    assert tc.trim_clip(seq, ASSETS, clip_id='slow', edge='left', new_time=13.0)['ok']
    assert (c['source_start'], c['source_end']) == (2.0, 9.0)


# ---- through the MCP tool: a step the validator refuses leaves the draft untouched ----

@pytest.fixture
def draft(tmp_path, monkeypatch):
    monkeypatch.setattr(td, 'UPLOAD_ROOT', tmp_path)
    room = tmp_path / 'room'; room.mkdir()
    (room / 'contents.json').write_text(json.dumps([{'id': 'c', 'timeline': {'sequence': _seq()}}]))
    (room / 'assets.json').write_text(json.dumps(list(ASSETS.values())))
    d = td.create_draft('room', 'c', 'job'); d['live_updates'] = True; td.save_draft(d)
    monkeypatch.setattr(m, 'ROOM_ID', 'room'); monkeypatch.setattr(m, 'DRAFT_ID', d['draft_id'])
    monkeypatch.setattr(m, 'JOB_ID', 'job'); monkeypatch.setattr(m, 'CONTENT_ID', 'c')
    return d


def tool(name, args): return json.loads(m._run_tool_thread(name, args)[0].text)
def live(): return td._read_contents_raw('room')[0]['timeline']['sequence']
def draft_seq(d): return td.load_draft('room', d['draft_id'])['sequence']


def test_batch_trim_on_speed_clips_publishes(draft):
    r = tool('apply_edits', {'operations': [
        {'name': 'trim_clip', 'args': {'clip_id': 'slow', 'edge': 'right', 'new_time': 20.0}},
        {'name': 'trim_clip', 'args': {'clip_id': 'fast', 'edge': 'left', 'new_time': 1.0}}]})
    assert r['ok'] and r.get('timeline_updated'), r
    _consistent(live(), 'slow'); _consistent(live(), 'fast')


def test_batch_refused_by_validator_is_not_kept_in_draft(draft, monkeypatch):
    def old_trim(seq, assets, *, clip_id, edge, new_time):   # the 11/18 behaviour: ignores speed
        c = _clip(seq, clip_id)
        c['source_end'] = round(c['source_start'] + (new_time - c['timeline_start']), 3)
        c['timeline_end'] = new_time
        return {'ok': True}
    real_trim = tc.trim_clip
    monkeypatch.setattr(tc, 'trim_clip', old_trim)
    before_live, before_draft = copy.deepcopy(live()), copy.deepcopy(draft_seq(draft))
    r = tool('apply_edits', {'operations': [
        {'name': 'trim_clip', 'args': {'clip_id': 'slow', 'edge': 'right', 'new_time': 20.0}}]})
    assert not r['ok'] and r.get('rolled_back') and not r.get('saved_in_draft'), r
    assert 'source span' in r['error']
    assert live() == before_live
    assert draft_seq(draft) == before_draft
    # the next edit is not blocked by the refused one
    monkeypatch.setattr(tc, 'trim_clip', real_trim)
    r = tool('trim_clip', {'clip_id': 'slow', 'edge': 'right', 'new_time': 20.0})
    assert r['ok'] and r.get('timeline_updated'), r
