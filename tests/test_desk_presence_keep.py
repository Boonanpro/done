import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import desk_presence_keep as d  # noqa: E402


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
