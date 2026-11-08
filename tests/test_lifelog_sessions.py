"""A conversation split by speaker again as a whole once it is over (app/services/lifelog_sessions.py).

The owner wants who-said-what as right as possible. In a noisy bar a voice speaks a few seconds per minute-long
recording, too little to be recognised again, so one person came out under several numbers and short replies took
the number of whoever spoke around them. Here the recordings of one conversation are split together (pyannote, in
its own Python: faked below), each short reply goes to the voice it sounds like, and the day is numbered again from
one voice per speaker of the conversation."""
import json

import numpy as np
import pytest

from app.services import lifelog
from app.services import lifelog_sessions as ls
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


def entry(day, name, words=None, turns=None, seconds=20.0):
    return {"start": f"{day}T{name[:2]}:{name[2:4]}:{name[4:6]}+09:00", "seconds": seconds, "v": 3, "text": "x",
            "audio": name + ".ogg", "turns": turns or [{"start": 0, "end": 1, "text": "x", "voice": "1"}],
            "voices": {"0": {"day_voice": "1", "s": 5.0, "e": voice(9).tolist()}}, **({"words": words} if words else {})}


def put(day, name, e):
    folder = lifelog.AUDIO_ROOT / day
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (name + ".ogg")).write_bytes(b"")
    (folder / (name + ".json")).write_text(json.dumps(e, ensure_ascii=False))


def test_recordings_with_a_pause_of_ten_minutes_are_two_conversations(root):
    day = "2026-11-07"
    for n in ("210000_0_u", "210500_0_u", "211600_0_u"):   # 5 min apart, then 11 min after the second ended
        put(day, n, entry(day, n))
    assert [[a.name[:6] for a, _ in g] for g in ls.conversations(day)] == [["210000", "210500"], ["211600"]]


def test_words_become_pieces_cut_at_pauses_length_and_sentence_ends():
    words = [[0.0, 0.4, "今日"], [0.45, 0.9, "忙しい"], [0.95, 1.2, "ですか？"], [1.3, 1.6, "うん"],
             [2.5, 2.8, "予約"], [2.85, 5.6, "入ってるのよ"]]
    got = [(p["s"], p["t"]) for p in ls.pieces({"words": words})]
    assert got == [(0.0, "今日忙しいですか？"), (1.3, "うん"), (2.5, "予約入ってるのよ")]
    # an entry written before words were kept: its turns are the pieces
    assert ls.pieces({"turns": [{"start": 0, "end": 3, "text": "そうですね", "voice": "2"}]})[0]["t"] == "そうですね"


def test_a_short_reply_inside_another_speakers_turn_goes_to_the_voice_it_sounds_like(monkeypatch):
    """pyannote gave the mama's 「いらっしゃいませ」 to the man talking around it; its own voice is the mama's."""
    # the samples carry the speaker (0.1 the man, 0.2 the mama) and the fake embedding reads it back
    y = np.full(16000 * 40, 0.1, np.float32)
    y[16000 * 8:int(16000 * 9.5)] = 0.2
    y[16000 * 20:] = 0.2
    monkeypatch.setattr(sp, "embed", lambda seg: voice(int(round(float(np.mean(seg)) * 10)), 0.2))
    words = [[t, t + 1.5, w] for t, w in ((0, "最近"), (2, "どう"), (4, "仕事"), (6, "忙しい"), (8, "いらっしゃいませ"),
                                          (12, "うん"), (14, "まあね"))]
    words += [[t, t + 1.5, "そうなのよ"] for t in (20, 23, 26, 29, 32, 35)]
    segs = [[0, 19, "A"], [19, 40, "B"]]   # pyannote: the man until 19 s, the mama after
    out = ls.label_pieces([y], [segs], [{"words": words}])[0]
    who = {p["s"]: p["spk"] for p in out}
    assert who[8] == "B" and [who[t] for t in (0, 2, 4, 6, 12, 14)] == ["A"] * 6 and who[20] == "B"


def test_speakers_of_one_recording_never_share_a_number_and_the_owner_is_named_once(root):
    """Two speakers of one conversation both close to the owner's voice: only the closer one is みきさん."""
    day = "2026-11-07"
    owner = voice(1)
    sp.save_people({"people": {"p_o": {"name": "みきさん", "owner": True, "x": [owner.tolist()]}}})
    brother = voice(1, 0.9)   # close to the owner's voice, not the same
    v_brother = brother.tolist()
    e = entry(day, "210000_0_u")
    e.update(session="k", turns=[{"start": 0, "end": 2, "text": "兄です", "spk": "A", "voice": None},
                                 {"start": 2, "end": 4, "text": "弟です", "spk": "B", "voice": None}],
             voices={"A": {"s": 2.0, "ss": 60.0, "e": owner.tolist()}, "B": {"s": 2.0, "ss": 40.0, "e": v_brother}})
    put(day, "210000_0_u", e)
    assert float(owner @ brother) >= sp.JOIN_PERSON   # the case: the brother alone would be named みきさん
    sp.replace_day(day)
    text = lifelog.read_day(day)[0]["text"]
    assert text.startswith("［みきさん］兄です［話者") and "みきさん］弟です" not in text


def test_a_short_turn_of_a_long_speaker_is_numbered_from_the_whole_conversation(root):
    """1 s in this recording, 60 s in the conversation: it is not a lone 「はい」 left as ［？］."""
    day = "2026-11-07"
    e = entry(day, "210000_0_u")
    e.update(session="k", turns=[{"start": 0, "end": 1, "text": "はい", "spk": "A", "voice": None}],
             voices={"A": {"s": 1.0, "ss": 60.0, "e": voice(3).tolist()}})
    put(day, "210000_0_u", e)
    sp.replace_day(day)
    assert lifelog.read_day(day)[0]["text"] == "［話者1］はい"


def test_the_owners_correction_survives_numbering_the_day_again(root):
    day = "2026-11-07"
    put(day, "210000_0_u", entry(day, "210000_0_u", turns=[{"start": 0, "end": 1, "text": "x", "voice": "1"}]))
    state = sp.day_state(day)
    state["voices"]["1"] = {"c": voice(9).tolist(), "s": 30.0, "not": ["p_x"]}
    sp.save_day(day, state)
    sp.replace_day(day)
    assert sp.day_state(day)["voices"]["1"]["not"] == ["p_x"]


def test_a_conversation_still_going_on_waits_and_a_finished_one_runs_once(root, monkeypatch):
    day = "2026-11-07"
    for n in ("210000_0_u", "210100_0_u"):
        put(day, n, entry(day, n))
    monkeypatch.setattr(ls, "available", lambda: True)
    ran = []
    def fake(group):
        ran.append(len(group))
        for audio, e in group:
            e["session"] = ls.key(group)
            audio.with_suffix(".json").write_text(json.dumps(e))
    monkeypatch.setattr(ls, "run_conversation", fake)
    monkeypatch.setattr(sp, "replace_day", lambda d: None)
    import time
    end = time.mktime(time.strptime("2026-11-07 210120", "%Y-%m-%d %H%M%S"))
    assert ls.run_day(day, now=end + 60) == 0 and ran == []           # a minute after: the talk may go on
    assert ls.run_day(day, now=end + ls.SESSION_GAP + 1) == 1 and ran == [2]
    assert ls.run_day(day, now=end + ls.SESSION_GAP + 99) == 0 and ran == [2]   # done once
    # one of its recordings written again by the live pass (no longer split as the conversation): done again
    e = json.loads((lifelog.AUDIO_ROOT / day / "210100_0_u.json").read_text())
    e.pop("session")
    (lifelog.AUDIO_ROOT / day / "210100_0_u.json").write_text(json.dumps(e))
    assert ls.run_day(day, now=end + ls.SESSION_GAP + 199) == 1 and ran == [2, 2]


def test_a_recording_with_no_words_stays_in_its_conversation_after_the_split(root):
    """11/9 night: a recording of noise had a voice but no words; once split its turns were empty, it left the
    conversation, the conversation's key changed and the night was split again."""
    day = "2026-11-07"
    for n in ("210000_0_u", "210100_0_u"):
        put(day, n, entry(day, n))
    g = ls.conversations(day)[0]
    k = ls.key(g)
    e = json.loads((lifelog.AUDIO_ROOT / day / "210100_0_u.json").read_text())
    e.update(turns=[], voices={}, session=k)
    (lifelog.AUDIO_ROOT / day / "210100_0_u.json").write_text(json.dumps(e))
    assert ls.key(ls.conversations(day)[0]) == k


def test_the_owners_name_goes_to_the_speaker_most_like_him_not_the_one_who_spoke_longest(root):
    """11/7 21:17-22:46 at the bar: the mama's voice (0.635 to the owner, 755 s) spoke longer than the owner (0.94,
    409 s) and took 「みきさん」. The name goes to the most owner-like speaker of the conversation, and only to it."""
    day = "2026-11-07"
    owner = voice(1)
    sp.save_people({"people": {"p_o": {"name": "みきさん", "owner": True, "x": [owner.tolist()]}}})
    rng = np.random.default_rng(5)
    def towards(target, sim):   # a voice with cosine `sim` to target
        r = rng.normal(size=192); r -= (r @ target) * target; r /= np.linalg.norm(r)
        return (sim * target + np.sqrt(1 - sim ** 2) * r).astype(np.float32)
    mama, him = towards(owner, 0.64), towards(owner, 0.94)
    for n, spks in (("211706_0_u", ("A", "B")), ("211800_0_u", ("A",))):   # the second recording has only the mama
        e = entry(day, n)
        e.update(session="k", turns=[{"start": i * 2, "end": i * 2 + 2, "text": s + "です", "spk": s, "voice": None}
                                     for i, s in enumerate(spks)],
                 voices={s: {"s": 2.0, "ss": {"A": 755.0, "B": 409.0}[s], "e": {"A": mama, "B": him}[s].tolist()}
                         for s in spks})
        put(day, n, e)
    sp.replace_day(day)
    rows = [r["text"] for r in lifelog.read_day(day)]
    assert "［みきさん］Bです" in rows[0] and "みきさん］Aです" not in rows[0] and "みきさん" not in rows[1]
