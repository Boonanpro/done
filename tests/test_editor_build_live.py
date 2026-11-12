"""新規作成した空の作品で、欄のダンが元の録画の区間を並べると1分ぶんずつ画面に出る（2026-11-12）。"""
import json

import pytest

import app.timeline_mcp_server as m
from app.services import timeline_draft as td


@pytest.fixture
def blank(tmp_path, monkeypatch):
    monkeypatch.setattr(td, 'UPLOAD_ROOT', tmp_path)
    monkeypatch.setattr(m.time, 'sleep', lambda s: None)
    room = tmp_path / 'room'; room.mkdir()
    (room / 'contents.json').write_text(json.dumps([{'id': 'c', 'format': '16:9', 'timeline': {}, 'updated_at': 'old'}]))
    (room / 'assets.json').write_text(json.dumps([{'id': 'rec', 'kind': 'video', 'metadata': {'duration': 5000}}]))
    return 'room'


def live(room):
    return td._read_contents_raw(room)[0]


def start(room, monkeypatch):
    assert td.ensure_sequence(room, 'c') is True
    assert td.ensure_sequence(room, 'c') is False
    d = td.create_draft(room, 'c', 'chat_x'); d['live_updates'] = True; td.save_draft(d)
    monkeypatch.setattr(m, 'ROOM_ID', room); monkeypatch.setattr(m, 'DRAFT_ID', d['draft_id'])
    return d


def run(name, args):
    return json.loads(m._run_tool_thread(name, args)[0].text)


def test_blank_work_gets_empty_timeline_and_rough_cut_publishes_in_steps(blank, monkeypatch):
    start(blank, monkeypatch)
    ranges = [{'source_start': i * 20.0, 'source_end': i * 20.0 + 15.0} for i in range(10)]   # 150秒
    res = run('append_clips', {'asset_id': 'rec', 'ranges': ranges})
    assert res['ok'] and res['placed'] == 10, res
    seq = live(blank)['timeline']['sequence']
    video = [t for t in seq['tracks'] if t['type'] == 'video'][0]['clips']
    assert [(c['source_start'], c['source_end']) for c in video] == [(r['source_start'], r['source_end']) for r in ranges]
    assert video[-1]['timeline_end'] == 150.0
    _, feed = td.read_edit_feed(blank, 'c', 0)
    assert len(feed) == 3          # 60秒ごとに2回 + 残り1回
    assert live(blank)['updated_at'] != 'old'
    # 続けて普通の道具も本番へ出る（途中で出した分の基準を引き継いでいる）
    res = run('append_clip', {'asset_id': 'rec', 'source_start': 4000, 'duration': 3})
    assert res['ok'] and res.get('timeline_updated'), res


def test_owner_edit_mid_rough_cut_stops_without_overwriting(blank, monkeypatch):
    start(blank, monkeypatch)
    real_sleep_calls = []

    def owner_edits(_s):
        if real_sleep_calls:
            return
        real_sleep_calls.append(1)
        contents = td._read_contents_raw(blank)
        contents[0]['timeline']['sequence']['tracks'][0]['clips'][0]['source_end'] = 1.0
        td._write_contents_raw(blank, contents)
    monkeypatch.setattr(m.time, 'sleep', owner_edits)
    ranges = [{'source_start': i * 20.0, 'source_end': i * 20.0 + 15.0} for i in range(10)]
    res = run('append_clips', {'asset_id': 'rec', 'ranges': ranges})
    assert not res['ok']
    assert live(blank)['timeline']['sequence']['tracks'][0]['clips'][0]['source_end'] == 1.0


def test_missing_asset_reports_and_places_nothing(blank, monkeypatch):
    start(blank, monkeypatch)
    res = run('append_clips', {'asset_id': 'nope', 'ranges': [{'source_start': 0, 'source_end': 5}]})
    assert not res['ok'] and 'asset not found' in json.dumps(res, ensure_ascii=False)
