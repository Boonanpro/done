"""Typing over suggestions and the owner's own suggestions on the listening screen (app/services/script_listen_marks.py)."""
import itertools

import pytest

from app.services import script_listen as S
from app.services import script_listen_marks as M
from tests.test_script_listen import _apply, _doc, _ends


def _toks(doc, a, b=None):
    return M.tokens(doc, a, a if b is None else b, S._chars)


def _body(doc):
    return ''.join(e['textRun']['content'] for el in doc['body']['content'] for e in el['paragraph']['elements'])


def _run(doc, para, new, mode, bm=None, sugs=()):
    view, placed = M.overlay(doc, list(sugs))
    toks, end = _toks(view, para)
    new_toks, settled = M.plan(toks, new, bm or '0' * len(new), mode)
    a, pos, abm, b, bbm, xlock, ops = M.doc_change(toks, new_toks)
    reqs = S.replace_requests(pos + [end], a, b, abm, bbm, ops) if a != b else []
    fresh = M.regroup(new_toks, para, ids=(f'o-{k}' for k in itertools.count()))
    return _apply(_body(doc), reqs), fresh, settled


def test_typing_over_dans_suggestion_keeps_it_a_suggestion():
    # 11/21 本人「承認や却下せずそのまま書き換えると、勝手に承認されて文字が本文に入ってしまう」
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'),
                     [('一括', {}, {}), ('で', {}, {'suggestedDeletionIds': ['s']}), ('なら', {}, {'suggestedInsertionIds': ['s']}),
                      ('36万円です。\n', {}, {})]))
    toks, _ = _toks(doc, 1)
    assert M.text_of(toks) == '一括でなら36万円です。'
    for typed in ('一括でなXら36万円です。', '一括だなら36万円です。', '一括なら36万円です。'):
        with pytest.raises(M.Adopt) as e:
            M.plan(toks, typed, '0' * len(typed), 'edit')
        assert e.value.sids == {'s'}
    # his suggestion as the owner's, with the same words
    pieces = S.adopt_pieces(doc, {'s'})
    assert [(x['pre'], x['del'], x['ins'], x['post'], x['from']['suggestion']) for x in pieces] == [('一括', 'で', 'なら', '36万円です。', 's')]
    # once it is taken back in the doc, the screen reads the same, and typing into it changes the suggestion only
    back = _ends(_doc(('◎台本\n', 'HEADING_2'), '一括で36万円です。\n'))
    for mode in ('edit', 'suggest'):
        body, fresh, settled = _run(back, 1, '一括でなXら36万円です。', mode, sugs=pieces)
        assert body == '◎台本\n一括で36万円です。\n' and not settled
        assert [(f['id'], f['del'], f['ins']) for f in fresh] == [(pieces[0]['id'], 'で', 'なXら')]
    # 承認 / 却下 still decide it
    view, _ = M.overlay(back, pieces)
    t2, end = _toks(view, 1)
    new_toks, _ = M.plan(t2, M.text_of(t2), M.bmask_of(t2), 'edit', force={pieces[0]['id']: True})
    a_, pos, abm, b_, bbm, _, ops = M.doc_change(t2, new_toks)
    assert _apply(_body(back), S.replace_requests(pos + [end], a_, b_, abm, bbm, ops)) == '◎台本\n一括なら36万円です。\n'


def test_a_suggestion_of_dans_across_paragraphs_is_not_rewritten():
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), [('前の文。', {}, {}), ('足す\n', {}, {'suggestedInsertionIds': ['s']}), ('後の文。\n', {}, {})]))
    with pytest.raises(S.ListenError):
        S.adopt_pieces(doc, {'s'})


def test_typing_next_to_a_suggestion_does_not_settle_it():
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), [('前の', {}, {}), ('古い', {}, {'suggestedDeletionIds': ['x']}), ('文です。\n', {}, {})]))
    body, fresh, settled = _run(doc, 1, 'すごく前の古い文です。', 'edit')
    assert body == '◎台本\nすごく前の古い文です。\n' and not settled and not fresh


def test_suggestion_mode_strikes_and_adds_without_writing_the_doc():
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), '今日は大事な話をします。\n'))
    body, fresh, _ = _run(doc, 1, '今日はとても大切な話をします。', 'suggest')
    assert body == _body(doc)
    assert [(s['del'], s['ins'], s['pre'], s['post']) for s in fresh] == [('大事', 'とても大切', '今日は', 'な話をします。')]
    # laid over the doc, it shows like a suggestion: struck 「大事」, added 「とても大切」, read as taken
    view, placed = M.overlay(doc, fresh)
    assert placed == {'o-0': 1}
    units = S.outline(view)
    for n, u in enumerate(units): u['n'] = n
    say = [u for u in units if u['kind'] == 'say'][0]
    assert say['speak'] == '今日はとても大切な話をします。'
    assert [(g['t'], g.get('ins'), g.get('del')) for g in say['segs']] == [
        ('今日は', None, None), ('大事', None, 'o-0'), ('とても大切', 'o-0', None), ('な話をします。', None, None)]
    assert [s['by'] for s in S.suggestions_of(units)] == ['owner']


def test_owner_suggestion_grows_while_typing_and_is_found_after_edits_elsewhere():
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), '最初の段落です。\n', '今日は大事な話をします。\n'))
    _, s1, _ = _run(doc, 2, '今日は重要な話をします。', 'suggest')
    assert [(s['del'], s['ins']) for s in s1] == [('大事', '重要')]
    # typing on in the added words keeps one suggestion
    view, placed = M.overlay(doc, s1)
    toks, _ = _toks(view, 2)
    assert M.text_of(toks) == '今日は大事重要な話をします。'
    new_toks, _ = M.plan(toks, '今日は大事とても重要な話をします。', '0' * 17, 'suggest')
    s2 = M.regroup(new_toks, 2, ids=iter(['o-new']))
    assert [(s['id'], s['del'], s['ins']) for s in s2] == [(s1[0]['id'], '大事', 'とても重要')]
    # taking its added words out again leaves the struck ones (as in Docs; 却下 takes the whole suggestion back)
    new_toks, _ = M.plan(toks, '今日は大事な話をします。', '0' * 12, 'suggest')
    assert [(s['id'], s['del'], s['ins']) for s in M.regroup(new_toks, 2)] == [(s1[0]['id'], '大事', '')]
    # a paragraph put in before it: still found by its words
    moved = _ends(_doc(('◎台本\n', 'HEADING_2'), '足した段落。\n', '最初の段落です。\n', '今日は大事な話をします。\n'))
    assert M.overlay(moved, s2)[1] == {s1[0]['id']: 3}
    # its words changed in the doc: not shown (kept, it comes back if the words do)
    changed = _ends(_doc(('◎台本\n', 'HEADING_2'), '最初の段落です。\n', '今日は別の話をします。\n'))
    assert M.overlay(changed, s2)[1] == {}


def test_editing_the_owners_suggestion_in_edit_mode_keeps_it_a_suggestion():
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), '今日は大事な話をします。\n'))
    _, sugs, _ = _run(doc, 1, '今日は重要な話をします。', 'suggest')
    body, fresh, settled = _run(doc, 1, '今日は大事重X要な話をします。', 'edit', sugs=sugs)   # typed inside 「重要」
    assert not settled and body == _body(doc)
    assert [(f['id'], f['del'], f['ins']) for f in fresh] == [(sugs[0]['id'], '大事', '重X要')]
    # typing right after it is plain typing next to it (it stays a suggestion)
    body, fresh, settled = _run(doc, 1, '今日は大事重要さな話をします。', 'edit', sugs=sugs)
    assert not settled and body == '◎台本\n今日は大事さな話をします。\n' and [(f['del'], f['ins']) for f in fresh] == [('大事', '重要')]
    # taking all its added words out leaves the struck ones (still a suggestion)
    body, fresh, settled = _run(doc, 1, '今日は大事な話をします。', 'edit', sugs=sugs)
    assert not settled and body == _body(doc) and [(f['del'], f['ins']) for f in fresh] == [('大事', '')]


def test_accepting_the_owners_suggestion_writes_it():
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), '今日は大事な話をします。\n'))
    _, sugs, _ = _run(doc, 1, '今日は重要な話をします。', 'suggest')
    view, _ = M.overlay(doc, sugs)
    toks, end = _toks(view, 1)
    for accept, want in ((True, '今日は重要な話をします。'), (False, '今日は大事な話をします。')):
        new_toks, _ = M.plan(toks, M.text_of(toks), M.bmask_of(toks), 'edit', force={sugs[0]['id']: accept})
        a, pos, abm, b, bbm, _, ops = M.doc_change(toks, new_toks)
        reqs = S.replace_requests(pos + [end], a, b, abm, bbm, ops) if a != b else []
        assert _apply(_body(doc), reqs) == '◎台本\n' + want + '\n'
        assert M.regroup(new_toks, 1) == []


def test_suggestion_mode_refuses_new_paragraphs():
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), '一つ目です。二つ目です。\n'))
    toks, _ = _toks(doc, 1)
    with pytest.raises(M.Refused):
        M.plan(toks, '一つ目です。\n二つ目です。', '0' * 13, 'suggest')


def test_a_doc_suggestion_next_to_the_same_letter_is_not_taken_for_the_change():
    # 「ab」 is Dan's added words, then a plain 「b」: deleting the plain 「b」 must not touch his suggestion
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), [('x', {}, {}), ('ab', {}, {'suggestedInsertionIds': ['s']}), ('bです。\n', {}, {})]))
    body, _, _ = _run(doc, 1, 'xabです。', 'edit')
    assert body == '◎台本\nxabです。\n'


def test_the_owners_change_goes_onto_what_dan_changed_meanwhile():
    base = '一つ目の文です。二つ目の文です。'
    theirs = '一つ目の文です。二つ目のとても長い文です。'
    ours = '一つ目の短い文です。二つ目の文です。'
    got = M.rebase(base, theirs, ours, '0' * len(ours), '0' * len(theirs))
    assert got and got[0] == '一つ目の短い文です。二つ目のとても長い文です。'
    assert M.rebase(base, '一つ目の文だ。二つ目の文です。', '一つ目の文ね。二つ目の文です。', '0' * 16, '0' * 15) is None


def test_owner_actions_keep_only_standing_screen_suggestions(tmp_path):
    import json
    from app.services import script_learning as L
    log = tmp_path / 'log.jsonl'
    rows = [{'at': '2026-11-20T10:00:00+0900', 'doc_id': 'd', 'action': 'suggest', 'suggestion': 'o-1', 'before': 'A', 'after': 'B'},
            {'at': '2026-11-20T10:00:05+0900', 'doc_id': 'd', 'action': 'suggest', 'suggestion': 'o-1', 'before': 'A', 'after': 'BB'},
            {'at': '2026-11-20T10:00:06+0900', 'doc_id': 'd', 'action': 'suggest', 'suggestion': 'o-2', 'before': 'C', 'after': 'D'},
            {'at': '2026-11-20T10:00:09+0900', 'doc_id': 'd', 'action': 'settle', 'suggestion': 'o-2'}]
    log.write_text('\n'.join(json.dumps(r) for r in rows))
    got = L.owner_actions('d', 0, 2e9, path=log)
    assert [(a['action'], a['after']) for a in got] == [('suggest', 'BB')]


def test_words_struck_on_the_screen_become_the_owners_deletion(tmp_path, monkeypatch):
    # suggestion mode: Backspace strikes the letters on the screen (they stay in its text, marked '1')
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), 'そしてこの動画です。\n'))
    doc['revisionId'], doc['_account'] = 'r1', 'a'
    monkeypatch.setattr(S, 'OWNER_SUGS', tmp_path / 'sugs.json')
    monkeypatch.setattr(S, 'STATE', tmp_path)
    monkeypatch.setattr(S, 'fetch', lambda d: doc)
    monkeypatch.setattr(S, '_follow', lambda d: None)
    def no_write(*a, **k): raise AssertionError('suggestion mode wrote the doc')
    monkeypatch.setattr(S, '_docs', no_write)
    text = 'そしてこの動画です。'
    r = S.replace('d', 1, 1, text, text, '0' * 10, '0' * 10, 'suggest', '0011000000')
    sugs = M.load(tmp_path / 'sugs.json', 'd')
    assert [(s['pre'], s['del'], s['ins']) for s in sugs] == [('そし', 'てこ', '')]
    # 「てこ」 struck and 「てこ」 typed after it: no suggestion, and the screen (showing both) must read the doc again
    r = S.replace('d', 1, 1, 'そしてこの動画です。', 'そしてこてこの動画です。', '0' * 10, '0' * 12, 'suggest', '0011' + '0' * 8)
    # (which 「てこ」 is the struck one cannot be told from the text; the screen is read again to show it as kept)
    assert r['reload']


def test_accept_all_takes_overlapping_suggestions_in_one_write(tmp_path, monkeypatch):
    # 「足す」 suggested with 「5」 inside it suggested out by another one (the doc of 11/20 had five of these)
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'),
                     [('前。', {}, {}), ('足す', {}, {'suggestedInsertionIds': ['a']}),
                      ('5', {}, {'suggestedInsertionIds': ['a'], 'suggestedDeletionIds': ['b']}),
                      ('文', {}, {'suggestedInsertionIds': ['a']}), ('古い', {}, {'suggestedDeletionIds': ['c']}), ('後。\n', {}, {})]))
    doc['revisionId'], doc['_account'] = 'r1', 'x'
    monkeypatch.setattr(S, 'OWNER_SUGS', tmp_path / 'sugs.json')
    monkeypatch.setattr(S, 'STATE', tmp_path)
    monkeypatch.setattr(S, 'fetch', lambda d: doc)
    monkeypatch.setattr(S, '_follow', lambda d: None)
    sent = []
    monkeypatch.setattr(S, '_docs', lambda m, path, acc, body=None, params=None: sent.append(body) or {})
    r = S.accept_all('d')
    assert r == {'accepted': 3, 'failed': 0}
    assert _apply(_body(doc), sent[0]['requests']) == '◎台本\n前。足す文後。\n'


@pytest.mark.parametrize('sid,accept,want', [
    ('a', False, '前。後。'),           # rejecting the added words takes all of them out (the inner one with them)
    ('a', True, '前。足す文後。'),      # taking them takes the inner taking-out too
    ('b', True, '前。足す文後。'),      # taking out words another one adds
])
def test_deciding_an_overlapping_suggestion(tmp_path, monkeypatch, sid, accept, want):
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'),
                     [('前。', {}, {}), ('足す', {}, {'suggestedInsertionIds': ['a']}),
                      ('5', {}, {'suggestedInsertionIds': ['a'], 'suggestedDeletionIds': ['b']}),
                      ('文', {}, {'suggestedInsertionIds': ['a']}), ('後。\n', {}, {})]))
    doc['revisionId'], doc['_account'] = 'r1', 'x'
    monkeypatch.setattr(S, 'STATE', tmp_path)
    monkeypatch.setattr(S, 'fetch', lambda d: doc)
    monkeypatch.setattr(S, '_follow', lambda d: None)
    sent = []
    monkeypatch.setattr(S, '_docs', lambda m, path, acc, body=None, params=None: sent.append(body) or {})
    S.decide('d', sid, accept)
    assert _apply(_body(doc), sent[0]['requests']) == '◎台本\n' + want + '\n'
    if sid == 'b':
        with pytest.raises(S.ListenError):     # keeping words someone adds as plain cannot be written
            S.decide('d', 'b', False)
