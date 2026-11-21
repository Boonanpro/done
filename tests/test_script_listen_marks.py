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


INS = {'suggestedInsertionIds': ['s']}


def _multi(*before):
    # Dan's suggestion adds two whole paragraphs (most of his suggestions in the 11/21 doc did)
    return _ends(_doc(('◎台本\n', 'HEADING_2'), *before, '前の文。\n', [('足す文です。\n', {}, INS)], [('二つ目です。\n', {}, INS)],
                      '後の文。\n'))


def test_typing_into_one_paragraph_of_dans_suggestion_across_paragraphs(tmp_path, monkeypatch):
    # 11/21 本人「提案モードの文章を編集できない…今は拒否される」(「この提案は段落をまたいでいるので…」)
    doc = _multi()
    toks, _ = _toks(doc, 3)
    with pytest.raises(M.Adopt):
        M.plan(toks, '二つX目です。', '0' * 7, 'edit')
    # only the paragraph being written becomes the owner's; the paragraph ends and the other paragraph stay his
    pieces = S.adopt_pieces(doc, {'s'}, paras={3})
    assert [(x['para'], x['pre'], x['del'], x['ins'], x['post'], x.get('above'), x.get('gap')) for x in pieces] == \
        [(3, '', '', '二つ目です。', '', '足す文です。', 0)]
    _, positions = S.adopt_plan(doc, {'s'}, paras={3}); reqs, _ = S.take_back_requests(doc, positions, [3])
    assert _apply(_body(doc), reqs) == '◎台本\n前の文。\n足す文です。\n\n後の文。\n'
    back = _ends(_doc(('◎台本\n', 'HEADING_2'), '前の文。\n', [('足す文です。\n', {}, INS)], [('\n', {}, INS)], '後の文。\n'))
    for mode in ('edit', 'suggest'):
        body, fresh, settled = _run(back, 3, '二つX目です。', mode, sugs=pieces)
        assert body == _body(back) and not settled
        assert [(f['id'], f['del'], f['ins']) for f in fresh] == [(pieces[0]['id'], '', '二つX目です。')]
    # paragraphs coming before it do not move it into another empty paragraph
    shifted = _ends(_doc(('◎台本\n', 'HEADING_2'), '\n', '\n', '前の文。\n', [('足す文です。\n', {}, INS)], [('\n', {}, INS)],
                         '後の文。\n'))
    _, placed = M.overlay(shifted, pieces)
    assert placed == {pieces[0]['id']: 5}


def test_replace_into_dans_suggestion_across_paragraphs(tmp_path, monkeypatch):
    doc = _multi()
    doc['revisionId'], doc['_account'] = 'r1', 'a'
    back = _ends(_doc(('◎台本\n', 'HEADING_2'), '前の文。\n', [('足す文です。\n', {}, INS)], [('\n', {}, INS)], '後の文。\n'))
    back['revisionId'], back['_account'] = 'r2', 'a'
    now = {'doc': doc}
    monkeypatch.setattr(S, 'OWNER_SUGS', tmp_path / 'sugs.json')
    monkeypatch.setattr(S, 'STATE', tmp_path)
    monkeypatch.setattr(S, 'fetch', lambda d: now['doc'])
    monkeypatch.setattr(S, '_follow', lambda d: None)
    sent = []
    def docs(m, path, acc, body=None, params=None):
        sent.append(body); now['doc'] = back; return {}
    monkeypatch.setattr(S, '_docs', docs)
    r = S.replace('d', 3, 3, '二つ目です。', '二つX目です。', '0' * 6, '0' * 7, 'edit')
    assert r['changed'] and len(sent) == 1                # the words taken back once; the change itself is a suggestion
    assert _apply(_body(doc), sent[0]['requests']) == _body(back)
    sugs = M.load(tmp_path / 'sugs.json', 'd')
    assert [(x['ins'], x['from']['suggestion']) for x in sugs] == [('二つX目です。', 's')]
    view, placed = S.view('d', back)[0], S.view('d', back)[2]
    assert M.text_of(_toks(view, 3)[0]) == '二つX目です。' and M.text_of(_toks(view, 2)[0]) == '足す文です。'


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


def test_a_rewritten_suggestion_of_dans_is_kept_for_the_learning(tmp_path):
    from app.services import script_learning as L
    log = tmp_path / 'log.jsonl'
    dan = {'by': 'dan', 'suggestion': 's', 'del': 'すぐ受け取れます', 'ins': 'XY'}
    rows = [{'at': '2026-11-21T01:00:00+0900', 'doc_id': 'd', 'action': 'adopt', 'suggestion': 'o-1', 'before': 'aすぐ', 'after': 'aXY', 'revised_from': dan},
            {'at': '2026-11-21T01:00:01+0900', 'doc_id': 'd', 'action': 'adopt', 'suggestion': 'o-2', 'before': 'b', 'after': 'c', 'revised_from': dan},
            {'at': '2026-11-21T01:00:05+0900', 'doc_id': 'd', 'action': 'suggest', 'suggestion': 'o-1', 'before': 'aすぐ', 'after': 'aXZY', 'revised_from': dan},
            {'at': '2026-11-21T01:00:05+0900', 'doc_id': 'd', 'action': 'settle', 'suggestion': 'o-2'},      # joined into o-1
            {'at': '2026-11-21T01:00:09+0900', 'doc_id': 'd', 'action': 'settle', 'suggestion': 'o-1', 'accept': True, 'revised_from': dan}]
    import json
    log.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows))
    out = L.owner_actions('d', 0, 2e9, path=log)
    got = [a for a in out if a['action'] == 'revised_suggestion']
    assert len(got) == 1 and got[0]['dan'] == dan and got[0]['owner_wording'] == {'before': 'aすぐ', 'after': 'aXZY'} and got[0]['accepted'] is True


def test_typing_into_dans_suggestion_inside_another_of_his():
    # 11/21 the doc's 「そして2つ目です。」: 「2」 suggested for 「5」 inside a suggested paragraph
    a, ab, a_b = {'suggestedInsertionIds': ['a']}, {'suggestedInsertionIds': ['b', 'a']}, {'suggestedInsertionIds': ['a'], 'suggestedDeletionIds': ['b']}
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), '前の文。\n',
                     [('そして', {}, a), ('2', {}, ab), ('5', {}, a_b), ('つ目です。\n', {}, a)], '後の文。\n'))
    toks, _ = _toks(doc, 2)
    assert M.text_of(toks) == 'そして25つ目です。'
    with pytest.raises(M.Adopt):
        M.plan(toks, 'そして25つ目ですね。', '0' * 11, 'edit')
    pieces, positions = S.adopt_plan(doc, {'a'}, paras={2})
    assert [(x['pre'], x['del'], x['ins'], x['post'], x['above'], sorted(x['from']['suggestions'])) for x in pieces] == \
        [('', '', 'そして2つ目です。', '', '前の文。', ['a', 'b'])]
    reqs, _ = S.take_back_requests(doc, positions, [2])
    assert _apply(_body(doc), reqs) == '◎台本\n前の文。\n\n後の文。\n'
    back = _ends(_doc(('◎台本\n', 'HEADING_2'), '前の文。\n', [('\n', {}, a)], '後の文。\n'))
    body, fresh, _ = _run(back, 2, 'そして2つ目ですね。', 'edit', sugs=pieces)
    assert body == _body(back) and [(f['del'], f['ins']) for f in fresh] == [('', 'そして2つ目ですね。')]


@pytest.mark.parametrize('typed,want', [
    ('そして25Xつ目です。', 'そして2Xつ目です。'),     # next to 「5」, which goes with the adoption (11/21 on the screen: X was lost)
    ('そしてX25つ目です。', 'そしてX2つ目です。'),
    ('そして2つ目です。', 'そして2つ目です。'),         # 「5」 taken out: nothing more to change
])
def test_typing_next_to_words_that_go_with_the_adoption(tmp_path, monkeypatch, typed, want):
    a, ab, a_b = {'suggestedInsertionIds': ['a']}, {'suggestedInsertionIds': ['b', 'a']}, {'suggestedInsertionIds': ['a'], 'suggestedDeletionIds': ['b']}
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), '前の文。\n',
                     [('そして', {}, a), ('2', {}, ab), ('5', {}, a_b), ('つ目です。\n', {}, a)], '後の文。\n'))
    doc['revisionId'], doc['_account'] = 'r1', 'x'
    back = _ends(_doc(('◎台本\n', 'HEADING_2'), '前の文。\n', [('\n', {}, a)], '後の文。\n'))
    back['revisionId'], back['_account'] = 'r2', 'x'
    now = {'doc': doc}
    monkeypatch.setattr(S, 'OWNER_SUGS', tmp_path / 'sugs.json')
    monkeypatch.setattr(S, 'STATE', tmp_path)
    monkeypatch.setattr(S, 'fetch', lambda d: now['doc'])
    monkeypatch.setattr(S, '_follow', lambda d: None)
    def docs(m, path, acc, body=None, params=None):
        now['doc'] = back; return {}
    monkeypatch.setattr(S, '_docs', docs)
    S.replace('d', 2, 2, 'そして25つ目です。', typed, '0' * 10, '0' * len(typed), 'edit')
    assert [x['ins'] for x in M.load(tmp_path / 'sugs.json', 'd')] == [want]


def test_dans_replacement_keeps_its_order_when_it_becomes_the_owners():
    # Docs keeps 「なら」 (added) before 「で」 (struck). As the owner's suggestion it reads the same, so what is being
    # typed does not move and the screen's next write still fits (11/21 本人「編集してることが巻き戻される」)
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'),
                     [('一括', {}, {}), ('なら', {}, {'suggestedInsertionIds': ['s']}), ('で', {}, {'suggestedDeletionIds': ['s']}),
                      ('36万円です。\n', {}, {})]))
    toks, _ = _toks(doc, 1)
    order = S.adopt_order(doc, {'s'}, 1, 1)
    assert ''.join(toks[k]['ch'] for k in order) == '一括ならで36万円です。'
    assert S.carry_change(toks, order, '一括ならXで36万円です。', '0' * 12)[0] == '一括ならXで36万円です。'
    pieces = S.adopt_pieces(doc, {'s'})
    assert [(x['del'], x['ins'], x.get('lead'), x['who'], x['dwho']) for x in pieces] == [('で', 'なら', 2, 'dd', 'd')]
    back = _ends(_doc(('◎台本\n', 'HEADING_2'), '一括で36万円です。\n'))
    view, _ = M.overlay(back, pieces)
    assert M.text_of(_toks(view, 1)[0]) == '一括ならで36万円です。'
    # typing in his words: only the typed letter is the owner's; the rest stays drawn as his
    body, fresh, _ = _run(back, 1, '一括ならXで36万円です。', 'suggest', sugs=pieces)
    assert body == '◎台本\n一括で36万円です。\n'
    assert [(f['del'], f['ins'], f.get('lead'), f.get('who'), f.get('dwho')) for f in fresh] == [('で', 'ならX', 3, 'ddo', 'd')]
    view, _ = M.overlay(back, [{**fresh[0], 'id': pieces[0]['id']}])
    assert M.text_of(_toks(view, 1)[0]) == '一括ならXで36万円です。'
    segs = [(g['t'], g.get('who')) for u in S.outline(view) if u.get('para') == 1 for g in u['segs']]
    assert segs == [('一括', None), ('なら', 'dan'), ('X', None), ('で', 'dan'), ('36万円です。', None)]


def test_words_typed_in_front_of_struck_words_stay_in_front():
    # 11/21: typed before the words struck with them, they moved behind them once written
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), '実際に、飲んでいた方も。\n'))
    toks, _ = _toks(doc, 1)
    screen, dmask = '実際に、飲んでまえいた方も。', '0' * 9 + '11' + '0' * 3
    keep = [k for k in range(len(screen)) if dmask[k] != '1']
    new = ''.join(screen[k] for k in keep)
    assert new == '実際に、飲んでまえ方も。'
    struck = [k for k in range(len(screen)) if dmask[k] == '1']
    def lead(j1, j2):
        lo = keep[j1 - 1] + 1 if j1 > 0 else 0
        hi = keep[j2] if j2 < len(keep) else len(screen)
        here = [k for k in struck if lo <= k < hi]
        return sum(1 for k in keep[j1:j2] if k < here[0]) if here else 0
    new_toks, _ = M.plan(toks, new, '0' * len(new), 'suggest', lead_of=lead)
    fresh = M.regroup(new_toks, 1, ids=iter(['o-1']))
    assert [(f['del'], f['ins'], f.get('lead')) for f in fresh] == [('いた', 'まえ', 2)]
    view, _ = M.overlay(doc, fresh)
    assert M.text_of(_toks(view, 1)[0]) == screen
    # accepting it reads as typed
    t2, end = _toks(view, 1)
    nt, _ = M.plan(t2, M.text_of(t2), M.bmask_of(t2), 'edit', force={'o-1': True})
    a_, pos, abm, b_, bbm, _, ops = M.doc_change(t2, nt)
    assert _apply(_body(doc), S.replace_requests(pos + [end], a_, b_, abm, bbm, ops)) == '◎台本\n実際に、飲んでまえ方も。\n'


def test_owners_words_of_two_sentences_are_drawn_once():
    # 11/21: a whole paragraph of the owner's words (two sentences) showed both in the first sentence and the second
    # one again as plain text
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), '前の文。\n', [('\n', {}, {'suggestedInsertionIds': ['a']})], '後の文。\n'))
    sug = {'id': 'o-1', 'para': 2, 'pre': '', 'del': '', 'ins': '一つ目です。二つ目です。', 'bm': '', 'post': '', 'above': '前の文。', 'gap': 0}
    view, placed = M.overlay(doc, [sug])
    assert placed == {'o-1': 2}
    says = [u for u in S.outline(view) if u.get('para') == 2]
    assert [[(s['t'], s.get('ins')) for s in u['segs']] for u in says] == [[('一つ目です。', 'o-1')], [('二つ目です。', 'o-1')]]


def test_words_typed_on_both_sides_of_struck_words_keep_their_places(tmp_path, monkeypatch):
    # 11/21 on the screen: 「まえ」 typed in front of the struck 「かに」 and 「あと」 behind it read 「かに」「まえあと」 once written
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), '「たしかに、ちゃんと」\n'))
    doc['revisionId'], doc['_account'] = 'r1', 'a'
    monkeypatch.setattr(S, 'OWNER_SUGS', tmp_path / 'sugs.json')
    monkeypatch.setattr(S, 'STATE', tmp_path)
    monkeypatch.setattr(S, 'fetch', lambda d: doc)
    monkeypatch.setattr(S, '_follow', lambda d: None)
    def no_write(*a, **k): raise AssertionError('suggestion mode wrote the doc')
    monkeypatch.setattr(S, '_docs', no_write)
    old, screen = '「たしかに、ちゃんと」', '「たしまえかにあと、ちゃんと」'
    r = S.replace('d', 1, 1, old, screen, '0' * len(old), '0' * len(screen), 'suggest', '00000' + '11' + '0' * 9)
    sugs = M.load(tmp_path / 'sugs.json', 'd')
    assert [(s['del'], s['ins'], s.get('lead')) for s in sugs] == [('かに', 'まえあと', 2)]
    view, _ = M.overlay(doc, sugs)
    assert M.text_of(_toks(view, 1)[0]) == screen
    # then more typed right behind the struck words: still in its place
    r = S.replace('d', 1, 1, screen, '「たしまえかにごあと、ちゃんと」', '0' * len(screen), '0' * 16, 'suggest', '')
    sugs = M.load(tmp_path / 'sugs.json', 'd')
    view, _ = M.overlay(doc, sugs)
    assert M.text_of(_toks(view, 1)[0]) == '「たしまえかにごあと、ちゃんと」'
