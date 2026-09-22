from app.services import timeline_captions as c


def test_phrase_boundaries_preserve_words_and_full_script():
    text='女性と話しにくかったり、なぜか不安になる。インターネットポルノ中毒を説明します。'
    parts=c.chunk_text(text,12)
    assert ''.join(parts)==text
    for word in ('女性','にくかったり','なぜか','中毒'):
        assert any(word in part for part in parts)
    assert all(part.strip('。、！？\n ') for part in parts)


def test_supplied_word_times_avoid_audio_generation_and_keep_other_captions(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'render_speech_wav',lambda *a,**k: (_ for _ in ()).throw(AssertionError('must reuse timings')))
    outside={'id':'outside','text':'残す','timeline_start':20,'timeline_end':23}
    seq={'duration':23,'tracks':[{'type':'caption','clips':[outside.copy()]}]}
    result=c.auto_captions(seq,{},tmp_path,[{'t0':0,'t1':4,'text':'最初の場面です。'}],
        words=[[0,1,'最初の'],[1,3.5,'場面です']])
    assert result['ok'] and result['timing_source']=='supplied'
    assert outside in seq['tracks'][0]['clips']
    assert ''.join(s['text'] for s in result['specs'])=='最初の場面です。'
