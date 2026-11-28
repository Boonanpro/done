"""A save from an editor screen that was left open must not erase edits it has not seen.

2026-11-25: a tab that last synced at 07:01 saved at 10:53 and wrote its old timeline back,
erasing 72 changes Dan made at 07:10-07:25. The owner reopened the work and saw none of them."""
import asyncio
import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app.api.production_asset_routes as api
import app.services.timeline_authors as ta
import app.services.timeline_draft as td
from app.services import timeline_revs as tr

ROOM, CID = "room1", "c1"


def clip(cid, start, end, **kw):
    return {"id": cid, "timeline_start": start, "timeline_end": end, **kw}


def seq(*lanes, duration=10.0):
    return {"format": "16:9", "duration": duration, "tracks": [{"type": "video", "clips": list(c)} for c in lanes]}


def setup(tmp_path, monkeypatch, live):
    monkeypatch.setattr(api, "ASSET_ROOT", tmp_path)
    monkeypatch.setattr(td, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(ta, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr("app.services.clip_placement.normalize_contents", lambda *a, **k: None)
    (tmp_path / ROOM).mkdir(parents=True, exist_ok=True)
    api._write_contents(ROOM, [{"id": CID, "room_id": ROOM, "title": "t", "format": "16:9", "asset_ids": [],
                                "timeline": {"sequence": live}, "created_at": "x", "updated_at": "x"}])


def owner_save(sequence, base_rev):
    req = Request({"type": "http", "headers": [(b"x-timeline-actor", b"owner")]})
    data = api.SaveContentRequest(timeline={"sequence": sequence}, base_rev=base_rev)
    return asyncio.run(api.update_content(CID, data, req, room_id=ROOM, current_user=None))


def live_seq():
    return api._read_contents(ROOM)[0]["timeline"]["sequence"]


def ids(s):
    return {c["id"]: c for t in s["tracks"] for c in t["clips"]}


def test_stale_screen_save_keeps_dans_edits_and_applies_the_owners(tmp_path, monkeypatch):
    base = seq([clip("a", 0, 5, asset_id="old"), clip("b", 5, 10)], [clip("sfx1", 1, 2)])
    setup(tmp_path, monkeypatch, json.loads(json.dumps(base)))
    handed = asyncio.run(api.list_contents(room_id=ROOM, current_user=None))[0]["timeline"]["sequence"]
    rev = handed["_rev"]
    # Dan, after the screen loaded: replaces a's picture, adds a sound effect, removes sfx1
    dan = seq([clip("a", 0, 5, asset_id="new"), clip("b", 5, 10)], [clip("sfx2", 3, 4)])
    api._write_contents(ROOM, [{**api._read_contents(ROOM)[0], "timeline": {"sequence": dan}}])
    # the old screen: the owner moved b and added a caption; it still holds a's old picture and sfx1
    mine = json.loads(json.dumps(handed))
    mine["tracks"][0]["clips"][1] = clip("b", 6, 10)
    mine["tracks"][1]["clips"].append(clip("cap", 0, 1.0))
    owner_save(mine, rev)
    out = ids(live_seq())
    assert out["a"]["asset_id"] == "new"          # Dan's replacement stays
    assert "sfx2" in out and "sfx1" not in out     # Dan's addition and deletion stay
    assert out["b"]["timeline_start"] == 6         # the owner's move lands
    assert "cap" in out                            # the owner's addition lands
    assert "_rev" not in live_seq()


def test_save_from_the_current_version_is_written_as_is(tmp_path, monkeypatch):
    base = seq([clip("a", 0, 5), clip("b", 5, 10)])
    setup(tmp_path, monkeypatch, base)
    handed = asyncio.run(api.list_contents(room_id=ROOM, current_user=None))[0]["timeline"]["sequence"]
    mine = json.loads(json.dumps(handed))
    mine["tracks"][0]["clips"].pop()               # the owner deletes b
    res = owner_save(mine, handed["_rev"])
    assert list(ids(live_seq())) == ["a"]
    assert res["timeline"]["sequence"]["_rev"] == tr.rev_of(live_seq())


def test_unknown_base_is_refused_not_overwritten(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, seq([clip("a", 0, 5)]))
    with pytest.raises(HTTPException) as e:
        owner_save(seq([]), "0" * 40)
    assert e.value.status_code == 409
    assert list(ids(live_seq())) == ["a"]


def test_browser_number_format_counts_as_unchanged():
    base = seq([clip("a", 0.0, 5.0, scale=1.0)])
    mine = seq([clip("a", 0, 5, scale=1)])         # how the browser writes the same clip back
    live = seq([clip("a", 0.0, 5.0, scale=1.0, asset_id="dan")])
    out, stats = tr.merge(base, mine, live)
    assert ids(out)["a"]["asset_id"] == "dan" and stats["conflicts_owner_won"] == 0


def test_owner_moves_clip_dan_zooms_it_both_survive():
    """2026-11-28: the owner closed a gap (later clips moved) while Dan zoomed them; the owner's
    save wrote the old transform back. Different fields of one clip must both survive."""
    base = seq([clip("a", 10, 15, asset_id="rec", transform={"scale": 1.1}), clip("b", 15, 20, asset_id="rec")])
    live = seq([clip("a", 10, 15, asset_id="rec", transform={"scale": 2.4, "x": 0.1},
                     motion_keys=[{"t": 0, "scale": 1.1}]),
                clip("b", 15, 20, asset_id="blurred", source_start=3)])
    mine = seq([clip("a", 8, 13, asset_id="rec", transform={"scale": 1.1}), clip("b", 13, 18, asset_id="rec")])
    out, stats = tr.merge(base, mine, live)
    got = ids(out)
    assert got["a"]["timeline_start"] == 8 and got["a"]["timeline_end"] == 13
    assert got["a"]["transform"] == {"scale": 2.4, "x": 0.1} and got["a"]["motion_keys"]
    assert got["b"]["timeline_start"] == 13 and got["b"]["asset_id"] == "blurred" and got["b"]["source_start"] == 3


def test_field_both_changed_takes_the_owners():
    base = seq([clip("a", 0, 5, transform={"scale": 1})])
    live = seq([clip("a", 0, 5, transform={"scale": 2})])
    mine = seq([clip("a", 1, 5, transform={"scale": 3})])
    got = ids(tr.merge(base, mine, live)[0])
    assert got["a"]["transform"] == {"scale": 3} and got["a"]["timeline_start"] == 1
