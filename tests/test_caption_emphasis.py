from app.services import timeline_commands as tc


def _seq():
    return {"tracks": [{"type": "video", "clips": []}, {"type": "caption", "clips": []}]}


def test_emphasis_words_become_spans_with_scale():
    seq = _seq()
    r = tc.add_caption(seq, text="実は僕24年間鼻炎が治らなかった", timeline_start=0, timeline_end=2,
                       style={"emphasis": [{"text": "24年間", "color": "#e3141f", "scale": 1.4}]})
    assert r["ok"], r
    clip = [c for t in seq["tracks"] for c in t.get("clips", []) if c["id"] == r["clip_id"]][0]
    assert clip["style"]["colorSpans"] == [{"s": 3, "e": 7, "color": "#e3141f", "scale": 1.4}]
    assert "emphasis" not in clip["style"]


def test_set_clip_emphasis_replaces_and_clears_and_rejects_missing_word():
    seq = _seq()
    cid = tc.add_caption(seq, text="10年以上続けても全く治らず", timeline_start=0, timeline_end=2)["clip_id"]
    assert tc.set_clip(seq, clip_id=cid, style={"emphasis": [{"text": "全く治らず", "color": "#7b2cbf"}]})["ok"]
    clip = [c for t in seq["tracks"] for c in t.get("clips", []) if c["id"] == cid][0]
    assert clip["style"]["colorSpans"] == [{"s": 9, "e": 14, "color": "#7b2cbf"}]
    bad = tc.set_clip(seq, clip_id=cid, style={"emphasis": [{"text": "ない言葉", "color": "#f00"}]})
    assert not bad["ok"] and clip["style"]["colorSpans"][0]["s"] == 9
    assert tc.set_clip(seq, clip_id=cid, style={"emphasis": []})["ok"]
    assert "colorSpans" not in clip["style"]
