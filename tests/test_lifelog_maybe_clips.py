"""「みきさん？」 for a voice close to someone but not close enough to name, and the unnamed voices of a day with a clip
each (app/services/lifelog_speakers.py maybe_person, app/services/lifelog_clips.py; owner's request 2026-11-08)."""
import json
import shutil
import subprocess

import numpy as np
import pytest

from app.services import lifelog, lifelog_clips as lc, lifelog_speakers as sp


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(lifelog, "INDEX_ROOT", tmp_path / "index")
    monkeypatch.setattr(lifelog, "AUDIO_ROOT", tmp_path / "audio")
    monkeypatch.setattr(lifelog, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(sp, "SPEAKERS_ROOT", tmp_path / "speakers")
    monkeypatch.setattr(sp, "PEOPLE", tmp_path / "people.json")
    monkeypatch.setattr(lc, "CLIPS_ROOT", tmp_path / "clips")
    return tmp_path


def at(cos: float, seed: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Two unit voices whose cosine is `cos`: the same first one for every seed, a different second one per seed."""
    a = np.random.default_rng(0).normal(size=192); a /= np.linalg.norm(a)
    b = np.random.default_rng(seed).normal(size=192); b -= (b @ a) * a; b /= np.linalg.norm(b)
    return a.astype(np.float32), (cos * a + np.sqrt(1 - cos * cos) * b).astype(np.float32)


def book_with(owner: np.ndarray) -> dict:
    return {"people": {"p_me": {"name": "みきさん", "owner": True, "x": [owner.tolist()]}}}


def test_close_but_not_sure_shows_a_question_mark_far_stays_a_number(root):
    day = "2026-11-08"
    me, near = at(0.60)
    _, far = at(0.55, seed=2)       # other people came up to 0.575 on 11/6–11/8
    _, sure = at(0.70, seed=3)
    book = book_with(me)
    st = sp.day_state(day)
    k_near = sp.place(day, near, 40, st, book)
    k_far = sp.place(day, far, 40, st, book)
    k_sure = sp.place(day, sure, 40, st, book)
    assert sp.label(day, k_near, st, book) == "みきさん？"
    assert sp.label(day, k_far, st, book).startswith("話者")
    assert sp.label(day, k_sure, st, book) == "みきさん"


def test_short_voices_get_no_question_mark(root):
    day = "2026-11-08"
    me, near = at(0.60)
    book = book_with(me)
    st = {"voices": {"1": {"c": near.tolist(), "s": 10}}, "next": 2}
    assert not sp.refresh_maybe(st, book) and sp.label(day, "1", st, book) == "話者1"


def test_owner_says_not_him_and_the_question_mark_stays_off(root):
    day = "2026-11-08"
    me, near = at(0.60)
    sp.save_people(book_with(me))
    st = {"voices": {"1": {"c": near.tolist(), "s": 60}}, "next": 2}
    sp.save_day(day, st)
    lifelog.upsert_rows(day, [{"start": f"{day}T14:26:00+09:00", "seconds": 4, "audio": "/a/142600_000_x.ogg",
                               "text": "［話者1］友達の結婚式で", "plain": "友達の結婚式で",
                               "turns": [{"voice": "1", "text": "友達の結婚式で"}]}])
    sp.rerender_day(day)
    assert lifelog.read_day(day)[0]["text"] == "［みきさん？］友達の結婚式で"
    sp.forget_name(day, "1")
    assert lifelog.read_day(day)[0]["text"] == "［話者1］友達の結婚式で"
    sp.rerender_day(day)   # the voice book did not change its mind: still off
    assert lifelog.read_day(day)[0]["text"] == "［話者1］友達の結婚式で"
    assert sp.people()["people"]["p_me"]["x"]   # the owner's own examples are kept


def test_unnamed_lists_longest_first_and_picks_a_whole_readable_sentence(root):
    day = "2026-11-07"
    st = {"voices": {"6": {"c": at(0.9)[0].tolist(), "s": 3000, "who": "p_me"},
                     "75": {"c": at(0.1)[1].tolist(), "s": 500},
                     "43": {"c": at(0.1, 4)[1].tolist(), "s": 900, "guess": {"name": sp.MEDIA}},
                     "28": {"c": at(0.1, 5)[1].tolist(), "s": 230}}, "next": 100}
    sp.save_day(day, st)
    sp.save_people(book_with(at(0.9)[0]))
    assert [v["voice"] for v in lc.unnamed(day)] == ["75", "28"]
    s = [{"at": 75000, "start": 0, "end": 1.5, "text": "はい"},
         {"at": 75600, "start": 0, "end": 20, "text": "とても長い話をずっと続けている途中の言葉です"},
         {"at": 76300, "start": 0, "end": 5, "text": "そう本当にないかも美味しい"},
         {"at": 77000, "start": 0, "end": 5, "text": "聞き取れない音から作った言葉です"}]
    readable = lambda x: "" if "聞き取れない" in x["text"] else x["text"]
    assert [x["at"] for x in lc.pick(s, 2, check=readable)] == [76300, 75600]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg")
def test_a_clip_is_a_short_video_with_the_voice_sound(root, tmp_path):
    audio = tmp_path / "a.ogg"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=12",
                    "-c:a", "libopus", str(audio)], check=True)
    out = lc.make_clip("2026-11-07", "75", {"audio": str(audio), "at": 75600, "start": 1.0, "end": 15.0,
                                            "text": "じゃあこれお土産だ友達にあげたかったら"}, "話者75")
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of",
                                      "json", str(out)], capture_output=True, text=True).stdout)
    kinds = {s["codec_type"]: float(s["duration"]) for s in info["streams"]}
    assert out.suffix == ".mp4" and set(kinds) == {"video", "audio"}
    assert 8 <= kinds["audio"] <= 8.6 and kinds["video"] <= 9
