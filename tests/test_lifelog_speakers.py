"""Who said what in the lifelog (app/services/lifelog_speakers.py, scripts/lifelog_worker.py).

The owner's day is read back as 「［みきさん］…［スヤさん？］…［話者3］…」: the same voice keeps one number all day, a
known voice comes back with its name the next day, names given by the owner stick, Whisper's YouTube outros over
silence disappear, and a recording written before speakers existed is written again in place of its old row."""
import json
import types
from pathlib import Path

import numpy as np
import pytest

from app.services import lifelog
from app.services import lifelog_speakers as sp


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(lifelog, "INDEX_ROOT", tmp_path / "index")
    monkeypatch.setattr(lifelog, "AUDIO_ROOT", tmp_path / "audio")
    monkeypatch.setattr(lifelog, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(sp, "SPEAKERS_ROOT", tmp_path / "speakers")
    monkeypatch.setattr(sp, "PEOPLE", tmp_path / "people.json")
    return tmp_path


def voice(seed: int, noise: float = 0.0, rng=np.random.default_rng(0)) -> np.ndarray:
    base = np.random.default_rng(seed).normal(size=192)
    v = base / np.linalg.norm(base) + noise * rng.normal(size=192) / np.sqrt(192)
    return (v / np.linalg.norm(v)).astype(np.float32)


def test_words_go_to_their_speaker_and_overlap_stays_with_main_speaker():
    turns = [{"start": 0.0, "end": 6.0, "local": 0}, {"start": 2.0, "end": 2.6, "local": 1},
             {"start": 6.2, "end": 8.0, "local": 1}]
    words = [{"start": 0.1, "end": 0.5, "word": "今日"}, {"start": 2.1, "end": 2.5, "word": "結局"},
             {"start": 3.0, "end": 3.4, "word": "大事"}, {"start": 6.3, "end": 6.8, "word": "はい"}]
    out = sp.words_to_turns(words, turns)
    assert [(t["local"], t["text"]) for t in out] == [(0, "今日結局大事"), (1, "はい")]


def test_youtube_outro_over_silence_is_dropped_but_real_words_stay():
    assert sp.is_phantom("ご視聴ありがとうございました", 0.0)
    assert sp.is_phantom("ご視聴ありがとうございました。", 0.1)
    assert not sp.is_phantom("ご視聴ありがとうございました", 0.9)      # someone really said it
    assert not sp.is_phantom("ありがとうございました、助かりました", 0.0)


def test_same_voice_keeps_its_number_new_voice_gets_next(root):
    state, book = sp.day_state("2026-11-07"), sp.people()
    a = sp.place("2026-11-07", voice(1), 5, state, book)
    b = sp.place("2026-11-07", voice(2), 5, state, book)
    a2 = sp.place("2026-11-07", voice(1, 0.6), 3, state, book)
    assert (a, b, a2) == ("1", "2", "1")


def test_named_voice_comes_back_by_voice_the_next_day(root):
    day1, day2 = "2026-11-07", "2026-11-08"
    st = sp.day_state(day1)
    k = sp.place(day1, voice(7), 30, st, sp.people())
    sp.save_day(day1, st)
    sp.remember_voice(day1, k, "スヤさん", by="conversation")
    st2 = sp.day_state(day2)
    k2 = sp.place(day2, voice(7, 0.6), 4, st2, sp.people())
    assert sp.label(day2, k2, st2) == "スヤさん"
    other = sp.place(day2, voice(8), 4, st2, sp.people())
    assert sp.label(day2, other, st2) == f"話者{other}"


def test_guess_shows_with_question_mark_and_render_marks_speaker_changes(root):
    day = "2026-11-07"
    st = sp.day_state(day)
    st["voices"] = {"1": {"c": voice(1).tolist(), "s": 10, "guess": {"name": "スヤさん"}},
                    "2": {"c": voice(2).tolist(), "s": 10}}
    turns = [{"voice": "1", "text": "どうぞ"}, {"voice": "1", "text": "上がって"}, {"voice": "2", "text": "失礼します"}]
    assert sp.render(turns, day, st, {"people": {}}) == "［スヤさん？］どうぞ上がって［話者2］失礼します"


def test_owner_correction_and_not_rewrite_the_day(root):
    day = "2026-11-07"
    st = sp.day_state(day)
    k = sp.place(day, voice(3), 20, st, sp.people())
    sp.save_day(day, st)
    lifelog.upsert_rows(day, [{"start": f"{day}T13:05:18+09:00", "seconds": 4, "audio": "/a/130518_000_x.ogg",
                               "text": "", "plain": "失礼します", "turns": [{"voice": k, "text": "失礼します"}]}])
    # text empty -> no row; give it text
    lifelog.upsert_rows(day, [{"start": f"{day}T13:05:18+09:00", "seconds": 4, "audio": "/a/130518_000_x.ogg",
                               "text": f"［話者{k}］失礼します", "plain": "失礼します",
                               "turns": [{"voice": k, "text": "失礼します"}]}])
    sp.remember_voice(day, k, "中村さん", by="owner")
    assert lifelog.read_day(day)[0]["text"] == "［中村さん］失礼します"
    sp.forget_name(day, k)
    assert lifelog.read_day(day)[0]["text"] == f"［話者{k}］失礼します"
    assert sp.people()["people"][sp.person_by_name(sp.people(), "中村さん")]["x"] == []


def test_upsert_replaces_the_row_of_the_same_recording(root):
    day = "2026-11-07"
    lifelog.add_transcript({"start": f"{day}T13:05:18+09:00", "seconds": 4, "text": "古い", "audio": "/x/130518_000_u.ogg"})
    lifelog.add_transcript({"start": f"{day}T13:06:00+09:00", "seconds": 4, "text": "別", "audio": "/x/130600_000_u.ogg"})
    lifelog.upsert_rows(day, [{"start": f"{day}T13:05:18+09:00", "seconds": 4, "text": "［みきさん］新しい",
                               "audio": "/y/130518_000_u.ogg", "turns": [], "parts": [1]}])
    rows = lifelog.read_day(day)
    assert [r["text"] for r in rows] == ["［みきさん］新しい", "別"]
    assert "parts" not in rows[0]
    lifelog.upsert_rows(day, [{"start": f"{day}T13:06:00+09:00", "text": "", "audio": "/x/130600_000_u.ogg"}])
    assert [r["text"] for r in lifelog.read_day(day)] == ["［みきさん］新しい"]


def test_search_and_recent_still_read_the_text(root):
    day = "2026-11-07"
    lifelog.add_transcript({"start": f"{day}T13:05:18+09:00", "seconds": 4, "audio": "/a/1.ogg",
                            "text": "［みきさん］失礼します［話者2］どうぞ上がって", "turns": []})
    assert lifelog.search("どうぞ", date=day)[0]["start"].endswith("13:05:18+09:00")
    assert "［話者2］どうぞ" in lifelog.as_text(lifelog.read_day(day))


def test_owner_names_go_to_the_owner():
    assert sp.is_owner_name("本田さん") and sp.is_owner_name("ミキ") and not sp.is_owner_name("スヤさん")


def test_worker_rewrites_an_old_recording_in_place(root, monkeypatch):
    import importlib, sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    worker = importlib.import_module("lifelog_worker")
    day = "2099-01-01"
    monkeypatch.setattr(worker, "backfill_from", lambda: "2000-01-01")
    folder = lifelog.AUDIO_ROOT / day
    folder.mkdir(parents=True)
    audio = folder / "130518_000_u.ogg"
    audio.write_bytes(b"x")
    old = {"start": f"{day}T13:05:18+09:00", "seconds": 4, "text": "古い", "audio": str(audio), "parts": []}
    audio.with_suffix(".json").write_text(json.dumps(old, ensure_ascii=False))
    lifelog.add_transcript({k: old[k] for k in ("start", "seconds", "text", "audio")})
    monkeypatch.setattr(sp, "available", lambda: True)
    new = {**old, "text": "［みきさん］新しい", "turns": [{"voice": "1", "text": "新しい"}], "v": sp.VERSION}
    monkeypatch.setattr(sp, "transcribe", lambda model, a: new)
    worker.run_pass(None, set(), {})
    assert [r["text"] for r in lifelog.read_day(day)] == ["［みきさん］新しい"]
    assert json.loads(audio.with_suffix(".json").read_text())["v"] == sp.VERSION
    # a second pass leaves it alone
    monkeypatch.setattr(sp, "transcribe", lambda model, a: pytest.fail("written twice"))
    worker.run_pass(None, set(), {})


@pytest.mark.skipif(not sp.available(), reason="speaker models not on this machine")
def test_real_models_tell_two_people_apart_in_one_recording():
    """Two real voices of 11/7 put side by side (the advisor, then the owner) come out as two speakers."""
    a = Path.home() / ".dan/lifelog/audio/2026-11-07/172004_134_2582a188.ogg"
    b = Path.home() / ".dan/lifelog/audio/2026-11-07/172558_464_2582a188.ogg"
    if not (a.exists() and b.exists()):
        pytest.skip("recordings of 11/7 not here")
    x = np.concatenate([sp.load_audio(a)[: 16000 * 12], sp.load_audio(b)[: 16000 * 12]])
    turns, voices = sp.analyze(x)
    first = {t["local"] for t in turns if t["end"] < 11.5}
    second = {t["local"] for t in turns if t["start"] > 12.5}
    assert first and second and not (first & second)
