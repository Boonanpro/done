import json

from app.services import timeline_authors as ta
from app.services import timeline_draft as td


def _seq(start=0.0, src=0.0, extra_lane_below=False):
    tracks = [{"id": "lane_v", "type": "video", "clips": [
        {"id": "c1", "asset_id": "a", "timeline_start": start, "timeline_end": start + 5,
         "source_start": src, "source_end": src + 5}]},
        {"id": "lane_a", "type": "audio", "clips": [
            {"id": "s1", "asset_id": "b", "timeline_start": 1, "timeline_end": 2, "volume": 1}]}]
    if extra_lane_below:
        tracks.insert(0, {"id": "lane_new", "type": "video", "clips": []})
    return {"format": "16:9", "tracks": tracks}


def test_diff_words_and_lane_identity():
    assert ta.diff(_seq(), _seq()) == []
    # adding a lane below shifts indexes but moves nothing
    assert ta.diff(_seq(), _seq(extra_lane_below=True)) == []
    rows = ta.diff(_seq(), _seq(start=2.0))
    assert rows[0]["clip_id"] == "c1" and rows[0]["what"] == ["位置"]
    rows = ta.diff(_seq(), _seq(src=2.82))
    assert rows[0]["what"] == ["使う範囲"]


def test_record_owner_then_dan(tmp_path, monkeypatch):
    monkeypatch.setattr(ta, "UPLOAD_ROOT", tmp_path)
    room, content = "r1", "w1"
    ta.record(room, content, _seq(), _seq(src=2.82), ta.OWNER)
    last = ta.last_by(room, content)
    assert last["c1"]["kind"] == "owner" and last["c1"]["label"] == "みきさん"
    assert "s1" not in last
    ta.record(room, content, _seq(src=2.82), _seq(start=3, src=2.82),
              {"kind": "dan", "label": "ダン（並行作業「冒頭の直し」）", "job_id": "j1"}, tool="move_clip")
    last = ta.last_by(room, content, ["c1"])
    assert last["c1"]["label"].startswith("ダン（並行作業")
    hist = ta.history_text(room, content, "c1")
    assert [h["who"] for h in hist["history"]] == ["ダン（並行作業「冒頭の直し」）", "みきさん"]
    # c1 was moved again by a Dan, so it is no longer "the owner's shape"
    assert ta.owner_recent_text(room, content) == ""
    ta.record(room, content, _seq(start=3, src=2.82), _seq(start=6, src=2.82), ta.OWNER)
    assert "c1" in ta.owner_recent_text(room, content)


def test_commit_draft_records_dan(tmp_path, monkeypatch):
    monkeypatch.setattr(ta, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(td, "UPLOAD_ROOT", tmp_path)
    room = "r2"
    (tmp_path / room).mkdir()
    (tmp_path / room / "contents.json").write_text(json.dumps(
        [{"id": "w2", "timeline": {"sequence": _seq()}}]), encoding="utf-8")
    draft = td.create_draft(room, "w2", job_id="chat_abc")
    draft["actor"] = {"kind": "dan", "label": "ダン（会話）", "job_id": "chat_abc"}
    draft["sequence"]["tracks"][0]["clips"][0]["timeline_start"] = 4.0
    draft["sequence"]["tracks"][0]["clips"][0]["timeline_end"] = 9.0
    draft["log"].append({"tool": "move_clip"})
    td.save_draft(draft)
    assert td.commit_draft(room, draft["draft_id"], lambda s, r: [])["ok"]
    last = ta.last_by(room, "w2")
    assert last["c1"]["label"] == "ダン（会話）" and last["c1"]["tool"] == "move_clip"
    assert last["c1"]["what"] == ["位置"]
