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


def test_typing_over_dans_added_words_takes_his_suggestion_first():
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'),
                     [('一括', {}, {}), ('で', {}, {'suggestedDeletionIds': ['s']}), ('なら', {}, {'suggestedInsertionIds': ['s']}),
                      ('36万円です。\n', {}, {})]))
    toks, _ = _toks(doc, 1)
    assert M.text_of(toks) == '一括でなら36万円です。'
    with pytest.raises(M.Settle) as e:
        M.plan(toks, '一括でなXら36万円です。', '0' * 13, 'edit')      # typed inside 「なら」
    assert e.value.decisions == {'s': True}
    # once 「なら」 is taken in the doc, the change reads 一括なら36万円 -> 一括なXら36万円
    o, _, n, _ = M.drop_settled(toks, '一括でなXら36万円です。', '0' * 13, {'s': True})
    assert (o, n) == ('一括なら36万円です。', '一括なXら36万円です。')
    # typing over the struck 「で」 keeps the old word (reject)
    with pytest.raises(M.Settle) as e:
        M.plan(toks, '一括だなら36万円です。', '0' * 11, 'edit')
    assert e.value.decisions == {'s': False}
    o, _, n, _ = M.drop_settled(toks, '一括だなら36万円です。', '0' * 11, {'s': False})
    assert (o, n) == ('一括で36万円です。', '一括だ36万円です。')
    # taking the struck 「で」 out: it goes anyway when taken
    with pytest.raises(M.Settle) as e:
        M.plan(toks, '一括なら36万円です。', '0' * 10, 'edit')
    assert e.value.decisions == {'s': True}


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


def test_editing_the_owners_suggestion_in_edit_mode_takes_it():
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), '今日は大事な話をします。\n'))
    _, sugs, _ = _run(doc, 1, '今日は重要な話をします。', 'suggest')
    body, fresh, settled = _run(doc, 1, '今日は大事重X要な話をします。', 'edit', sugs=sugs)   # typed inside 「重要」
    assert settled == {sugs[0]['id']: True}
    assert body == '◎台本\n今日は重X要な話をします。\n' and not fresh
    # typing right after it is plain typing next to it (it stays a suggestion)
    body, fresh, settled = _run(doc, 1, '今日は大事重要さな話をします。', 'edit', sugs=sugs)
    assert not settled and body == '◎台本\n今日は大事さな話をします。\n' and [(f['del'], f['ins']) for f in fresh] == [('大事', '重要')]
    # typing into its struck words keeps the old words (and the change)
    body, fresh, settled = _run(doc, 1, '今日は大だ事重要な話をします。', 'edit', sugs=sugs)
    assert settled == {sugs[0]['id']: False}
    assert body == '◎台本\n今日は大だ事な話をします。\n' and not fresh


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
