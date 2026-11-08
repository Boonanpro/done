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
    assert not sp.is_phantom("ご視聴ありがとうございました", 0.9, 2.5, -0.3)      # someone really said it
    assert not sp.is_phantom("ありがとうございました、助かりました", 0.0)
    # 11/7 20:45: stretched over 30 s with speech-like noise under it; 13:12: a short outro Whisper was unsure of
    assert sp.is_phantom("ご視聴ありがとうございました", 0.8, 30.0, -0.68)
    assert sp.is_phantom("では、次の動画でお会いしましょう。", 0.8, 2.0, -0.91)
    assert not sp.is_phantom("では、始めましょう", 0.0, 1.0)


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
    monkeypatch.setattr(sp, "transcribe", lambda model, a, old=None: new)
    worker.run_pass(None, set(), {})
    assert [r["text"] for r in lifelog.read_day(day)] == ["［みきさん］新しい"]
    assert json.loads(audio.with_suffix(".json").read_text())["v"] == sp.VERSION
    # a second pass leaves it alone
    monkeypatch.setattr(sp, "transcribe", lambda model, a, old=None: pytest.fail("written twice"))
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


def test_names_from_the_talk(root, monkeypatch):
    """The language model's answer: the owner named himself, a guest was called once, a voice is a video."""
    day = "2026-11-07"
    st = sp.day_state(day)
    for k, seed in (("1", 1), ("2", 2), ("3", 3), ("4", 4)):
        st["voices"][k] = {"c": voice(seed).tolist(), "s": 60.0}
    sp.save_day(day, st)
    turns = [{"voice": "1", "text": "本田です"}, {"voice": "2", "text": "どうぞ"}, {"voice": "3", "text": "中村です"},
             {"voice": "4", "text": "皆さん筋トレ頑張っていきましょう"}]
    lifelog.upsert_rows(day, [{"start": f"{day}T20:52:16+09:00", "seconds": 9, "audio": "/a/205216_0_u.ogg",
                               "text": sp.render(turns, day), "turns": turns}])
    answer = {"names": [{"voice": "1", "name": "本田さん", "sure": True, "quote": "本田です"},
                        {"voice": "2", "name": "スヤさん", "sure": False, "quote": "スヤさん、どうぞ"},
                        {"voice": "3", "name": "中村さん", "sure": True, "quote": "中村です"},
                        {"voice": "4", "media": True, "quote": "皆さん筋トレ頑張っていきましょう"}]}

    class Fake:
        def __init__(self, **kw):
            self.responses = types.SimpleNamespace(create=lambda **kw: types.SimpleNamespace(output_text=json.dumps(answer)))

    import openai
    monkeypatch.setattr(openai, "OpenAI", Fake)
    monkeypatch.setattr(sp, "_openai_key", lambda: "k")
    monkeypatch.setattr(sp, "calendar_lines", lambda d: "")
    sp.name_day(day)
    assert lifelog.read_day(day)[0]["text"] == "［みきさん］本田です［スヤさん？］どうぞ［中村さん］中村です［動画・放送の音？］皆さん筋トレ頑張っていきましょう"
    book = sp.people()["people"]
    assert sorted(p["name"] for p in book.values()) == ["みきさん", "中村さん"]
    assert [p for p in book.values() if p["name"] == "みきさん"][0]["owner"]


def test_written_again_reuses_one_voice_text_but_not_an_outro(root, monkeypatch):
    """A past recording with one voice keeps its text (no Whisper); one whose text is only an outro is heard again."""
    folder = lifelog.AUDIO_ROOT / "2026-11-07"
    folder.mkdir(parents=True)
    audio = folder / "131218_000_u.ogg"
    monkeypatch.setattr(sp, "load_audio", lambda a: np.zeros(16000 * 3, np.float32))
    monkeypatch.setattr(sp, "available", lambda: True)
    monkeypatch.setattr(sp, "analyze", lambda x: ([{"start": 0.0, "end": 2.0, "local": 0}], {0: (voice(1), 2.0, -30.0)}))
    calls = []

    class Model:
        def transcribe(self, *a, **kw):
            calls.append(1)
            return [types.SimpleNamespace(start=0.0, end=2.0, text="では、次の動画でお会いしましょう。", avg_logprob=-0.91,
                                          words=[])], types.SimpleNamespace(duration=3.0)

    plain_old = {"parts": [{"start": 0.0, "end": 2.0, "text": "鍵は閉めて大丈夫でしょうか"}]}
    assert sp.transcribe(Model(), audio, old=plain_old)["plain"] == "鍵は閉めて大丈夫でしょうか" and not calls
    outro_old = {"parts": [{"start": 0.0, "end": 2.0, "text": "では、次の動画でお会いしましょう。"}]}
    assert sp.transcribe(Model(), audio, old=outro_old)["text"] == "" and calls
