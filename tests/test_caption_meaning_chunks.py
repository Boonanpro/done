"""Captions split at meaning boundaries, start on the voice, and carry emphasis kinds.
2026-11-13 owner: the Suya captions were cut mid-phrase ('勝手にアプリや／ホームページを作ったわけでは')
and every caption looked the same."""
from app.services import timeline_captions as c


def _breaks(text, maxlen=16):
    return c.chunk_text(text, maxlen)


def test_coordinated_nouns_and_modifiers_stay_together():
    parts = _breaks('別にAIが自らお金を稼ごうとしたわけでも、勝手にアプリやホームページを作ったわけではありませんよね。')
    assert any('アプリやホームページ' in p for p in parts)
    parts = _breaks('この順番で取り組んだ人だけが、実践的にAIを使いこなせるようになって、収入や資産も最短最速で増やすことができます。')
    assert not any(p.endswith('ように') for p in parts)
    assert any('使いこなせるようになって' in p for p in parts)
    for text, keep in [('では、なぜAIで稼ぐために勉強より先に事業を始める必要があるのか。', '勉強より先に'),
                       ('このAIの波に乗って大きく資産を増やして、経済的に自由な生活を手に入れたい。', '大きく資産を')]:
        assert any(keep in p for p in _breaks(text)), (keep, _breaks(text))


def test_run_on_transcript_breaks_at_clause_not_inside_noun_phrase():
    parts = _breaks('結論から言うとこのAIの大波に乗って数千万、1億と稼ぎ自由な人生を手に入れたいなら')
    assert not any(p.endswith('この') or p.endswith('自由な') for p in parts)
    assert any(p.endswith('乗って') for p in parts)


def test_every_caption_fits_one_line():
    text = '実際僕も、この1年で太陽光発電やホームページ制作事業などをAIを使って改良し、数百万円から数千万円の規模で何度か売却しています。'
    parts = _breaks(text)
    assert c._norm(''.join(parts)) == c._norm(text)
    assert all(c._width(p) <= 16.2 for p in parts)


def test_markup_kinds_and_forced_breaks():
    chunks = c.chunk_script('でも断言しますが、<neg>それは間違ってます。</neg>勉強より先に<key>事業を始めてください。</key>|以上')
    assert [(x['text'], x['kind']) for x in chunks] == [
        ('でも断言しますが', 'normal'), ('それは間違ってます', 'neg'), ('勉強より先に', 'normal'),
        ('事業を始めてください', 'key'), ('以上', 'normal')]


def test_captions_start_on_the_voice_and_hold_through_short_pauses(tmp_path):
    words = [[0.5, 1.0, 'でも'], [1.0, 2.0, '断言しますが'], [2.3, 3.6, 'それは間違ってます'],
             [5.0, 6.0, '勉強より先に'], [6.1, 7.4, '事業を始めてください']]
    seq = {'duration': 10, 'tracks': []}
    r = c.auto_captions(seq, {}, tmp_path, [{'t0': 0, 't1': 9, 'text':
        'でも断言しますが、<neg>それは間違ってます。</neg>勉強より先に<key>事業を始めてください。</key>'}],
        words=words, style={'font': 'noto-sans', 'fontSize': 1.32, 'outlineColor': '#000000'})
    assert r['ok']
    sp = r['specs']
    assert [s['text'] for s in sp] == ['でも断言しますが', 'それは間違ってます', '勉強より先に', '事業を始めてください']
    assert sp[0]['start'] == 0.5 and sp[1]['start'] == 2.3 and sp[2]['start'] == 5.0
    assert sp[0]['end'] == sp[1]['start']            # 0.3 s pause: no blank flash
    assert abs(sp[1]['end'] - 3.85) < 1e-6          # long pause: lingers briefly, then clears
    clips = [x for t in seq['tracks'] if t['type'] == 'caption' for x in t['clips']]
    by_text = {x['text']: x for x in clips}
    neg = by_text['それは間違ってます'].get('style') or by_text['それは間違ってます'].get('caption_style') or {}
    key = by_text['事業を始めてください'].get('style') or by_text['事業を始めてください'].get('caption_style') or {}
    norm = by_text['でも断言しますが'].get('style') or by_text['でも断言しますが'].get('caption_style') or {}
    assert neg.get('color', '').upper() == '#FF4A4A' and neg.get('font') == 'dela-gothic'
    assert key.get('color', '').upper() == '#FFD84D'
    assert key.get('fontSize') > norm.get('fontSize')


def test_kind_style_override_and_unknown_font_rejected(tmp_path):
    seq = {'duration': 4, 'tracks': []}
    r = c.auto_captions(seq, {}, tmp_path, [{'t0': 0, 't1': 4, 'text': '<key>決め言葉</key>'}],
                        words=[[0, 1, '決め言葉']], styles={'key': {'font': 'Hiragino Sans'}})
    assert not r['ok']
    r = c.auto_captions(seq, {}, tmp_path, [{'t0': 0, 't1': 4, 'text': '<key>決め言葉</key>'}],
                        words=[[0, 1, '決め言葉']], styles={'key': {'color': '#00FF00'}})
    assert r['ok'] and r['styles']['key']['color'] == '#00FF00'


def test_hand_split_cards_are_kept_and_checked(tmp_path):
    text = '勝手にアプリや|ホームページを作ったわけでは|ありませんよね。|<key>AIは単なる労働力です。</key>'
    warn = c.lint_cards(text)
    assert any('アプリや｜ホームページ' in w for w in warn)
    words = [[0, 1, '勝手にアプリや'], [1, 2.2, 'ホームページを作ったわけでは'], [2.2, 3, 'ありませんよね'], [3.5, 5, 'AIは単なる労働力です']]
    seq = {'duration': 6, 'tracks': []}
    r = c.auto_captions(seq, {}, tmp_path, [{'t0': 0, 't1': 6, 'text': text}], words=words)
    assert r['ok'] and [s['text'] for s in r['specs']] == ['勝手にアプリや', 'ホームページを作ったわけでは', 'ありませんよね', 'AIは単なる労働力です']
    assert r['warnings']
    assert not c.lint_cards('勝手にアプリやホームページを|作ったわけではありませんよね。')
