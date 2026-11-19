import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import desk_presence_keep as d  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_log(monkeypatch, tmp_path):
    # 本物の記録（~/.dan/workspace/data/desk-presence-keep）に試験の行を書かない
    monkeypatch.setattr(d, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(d, "LOG_FILE", tmp_path / "log.jsonl")


def ev(s, e):
    return {"start_time": s, "end_time": e}


def test_merge_and_pad():
    now = 1_000_000
    m, open_now, last = d.presence_intervals([ev(1000, 1100), ev(1300, 1400), ev(5000, 5100)], now)
    assert m == [[1000 - d.PRE, 1400 + d.POST], [5000 - d.PRE, 5100 + d.POST]]
    assert not open_now and last == 5100


def test_forced_end_is_clamped_to_next_start():
    # 3つの印が同じ時刻（再起動）でまとめて閉じられた -> 次の印の始まりで切る
    forced = 900_000
    evs = [ev(1000, forced), ev(20_000, forced), ev(50_000, forced), ev(60_000, 60_100)]
    m, _, _ = d.presence_intervals(evs, 1_000_000)
    total = sum(e - s for s, e in m)
    assert total < 4 * d.UNKNOWN_END_CAP
    assert all(e - s <= d.UNKNOWN_END_CAP + d.PRE + d.POST + d.MERGE_GAP * 2 for s, e in m)


def test_open_event_is_owner_present():
    now = 1_000_000
    m, open_now, _ = d.presence_intervals([ev(now - 100, None)], now)
    assert open_now and m == []


def test_export_range_parse_is_utc():
    x = {"camera": "desk", "video_path": "/media/frigate/exports/desk_20261002_114454-20261002_115306_wjei99.mp4"}
    (s, e, _), = d.export_ranges([x])
    assert e - s == 8 * 60 + 12
    import datetime as dt
    assert dt.datetime.fromtimestamp(s, dt.timezone.utc).hour == 11


def test_covered():
    r = [(0, 100, {}), (150, 200, {})]
    assert d.covered(0, 100, r) == 1
    assert 0.6 < d.covered(0, 200, r) < 0.8


def test_exports_are_kept_without_limit(monkeypatch):
    """本人 11/18「180日より長く残したい」: 期限なしの時は1年前の書き出しも消さない。"""
    calls = []
    monkeypatch.setattr(d, "api", lambda *a, **k: calls.append(a) or (200, {}))
    old = {"id": "x", "name": "desk zaiseki 10-02 1926-2041", "in_progress": False}
    monkeypatch.setattr(d, "export_ranges", lambda ex: [(0.0, 100.0, old)])
    assert d.KEEP_DAYS is None
    assert d.delete_old_exports([old], now=400 * 86400, dry=False) == 0
    assert calls == []
    monkeypatch.setattr(d, "KEEP_DAYS", 180)
    assert d.delete_old_exports([old], now=400 * 86400, dry=False) == 1


def test_long_interval_is_split_into_chunks():
    """11/19: 1時間を超える区間は満杯の NAS で空きが足りず毎時止まった -> 30分以内に分ける。"""
    ch = d.split_chunks(0, 84 * 60)
    assert len(ch) == 3 and ch[0][0] == 0 and ch[-1][1] == 84 * 60
    assert all(b - a <= d.CHUNK_SEC for a, b in ch)
    assert d.split_chunks(0, 60) == [(0, 60)]


def test_pending_chunks_skip_exported_parts():
    st = {"failed": {}}
    now = 10_000_000
    iv = [[0.0, 3600.0]]
    ranges = [(0.0, 1800.0, {})]
    p = d.pending_chunks(iv, ranges, st, oldest_rec=0, now=now)
    assert p == [(1800.0, 3600.0)]
    assert d.pending_chunks(iv, [(0.0, 3600.0, {})], st, 0, now) == []


def test_retain_only_closed_short_events_in_pending():
    evs = [{"id": "a", "start_time": 100, "end_time": 200},
           {"id": "open", "start_time": 150, "end_time": None},
           {"id": "long", "start_time": 0, "end_time": 10 * 3600},
           {"id": "far", "start_time": 9000, "end_time": 9100}]
    assert d.retain_wanted(evs, [(90.0, 300.0)]) == {"a"}


def test_sync_retain_removes_only_its_own(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(d, "api", lambda m, p, *a, **k: calls.append((m, p)) or (200, {}))
    monkeypatch.setattr(d, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(d, "LOG_FILE", tmp_path / "l.jsonl")
    st = {"failed": {}, "retained": ["old"]}
    evs = [{"id": "a", "start_time": 100, "end_time": 200}]
    d.sync_retain(st, evs, [(90.0, 300.0)])
    assert ("POST", "/api/events/a/retain") in calls
    assert ("DELETE", "/api/events/old/retain") in calls
    assert st["retained"] == ["a"]


def test_low_space_waits_for_frigate_then_exports(monkeypatch, tmp_path):
    """空きが足りない時は止めずに Frigate の空け直しを待ってから書き出す。"""
    monkeypatch.setattr(d, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(d, "LOG_FILE", tmp_path / "l.jsonl")
    frees = iter([3000.0, 3000.0, 9000.0, 9000.0])
    monkeypatch.setattr(d, "storage_free_mib", lambda: next(frees))
    monkeypatch.setattr(d.time, "sleep", lambda s: None)
    now = 1_800_000_000.0
    monkeypatch.setattr(d.time, "time", lambda: now)
    monkeypatch.setattr(d, "get", lambda path, timeout=60: (
        [{"day": "2026-01-01"}] if "summary" in path else [] if "exports" in path else []))
    monkeypatch.setattr(d, "fetch_events", lambda after: [])
    monkeypatch.setattr(d, "presence_intervals", lambda ev, n: ([[now - 7200, now - 5400]], False, 0))
    monkeypatch.setattr(d, "bandwidth_mib_per_h", lambda: 4500.0)
    monkeypatch.setattr(d, "recorded_seconds", lambda s, e: e - s)
    done = []
    monkeypatch.setattr(d, "export_one", lambda s, e, r: done.append((s, e)) or (True, "x1"))
    monkeypatch.setattr(d, "sync_retain", lambda *a: None)
    monkeypatch.setattr(d, "reconcile_exports", lambda *a: None)

    class A:
        plan = False
        max = 0
        manage_retention = False
    # 時計を進めて待ちの打ち切りを確かめられるよう、呼ぶたびに少し進める
    t = [now]
    monkeypatch.setattr(d.time, "time", lambda: (t.__setitem__(0, t[0] + 1) or t[0]))
    assert d.run(A()) == 0
    assert done == [(now - 7200, now - 5400)]
