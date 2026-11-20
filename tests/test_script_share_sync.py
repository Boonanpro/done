"""The customer's copy follows the working doc by itself (app/services/script_share.py, 11/21 本人「俺が原本編集したら
中村さんの方にもそれが反映されて書き換わる？それができることが重要」)."""
from app.services import script_listen as S
from app.services import script_listen_marks as M
from app.services import script_share as SH
from tests.test_script_listen import _apply, _doc, _ends


def _text(doc):
    return ''.join(e['textRun']['content'] for el in doc['body']['content'] for e in el['paragraph']['elements'])


def _paras(*texts):
    return _ends(_doc(*[t + '\n' for t in texts]))


def _write(copy, P, W_doc, held=()):
    W = SH.paragraphs(W_doc)
    reqs, done, left = SH.copy_requests(copy, P, SH.paragraphs(copy, confirmed=False), W, held)
    return _apply(_text(copy), reqs), done, left


def test_the_owners_changes_go_into_the_copy_and_what_the_customer_wrote_stays():
    P = ['タイトル', '一つ目の文です。', '二つ目の文です。', '三つ目の文です。']
    copy = _paras('タイトル', '一つ目の文です。', '中村さんが直した二つ目。', '三つ目の文です。')
    work = _paras('タイトル', '一つ目の文を直しました。', '二つ目の文です。', '足した段落です。', '三つ目の文です。')
    out, done, left = _write(copy, P, work)
    assert out == 'タイトル\n一つ目の文を直しました。\n中村さんが直した二つ目。\n足した段落です。\n三つ目の文です。\n'
    assert done == 2 and left == 0


def test_suggested_words_in_the_working_doc_are_not_written():
    P = ['一括で36万円です。']
    copy = _paras('一括で36万円です。')
    work = _ends(_doc([('一括', {}, {}), ('で', {}, {'suggestedDeletionIds': ['s']}), ('なら', {}, {'suggestedInsertionIds': ['s']}),
                       ('36万円です。\n', {}, {})]))
    out, done, _ = _write(copy, P, work)
    assert out == '一括で36万円です。\n' and done == 0


def test_taking_paragraphs_out_and_the_last_paragraph():
    P = ['一つ目。', '二つ目。', '三つ目。']
    copy = _paras(*P)
    out, done, _ = _write(copy, P, _paras('一つ目。', '三つ目。'))
    assert out == '一つ目。\n三つ目。\n'
    out, _, _ = _write(copy, P, _paras('一つ目。', '二つ目。'))
    assert out == '一つ目。\n二つ目。\n'
    out, _, _ = _write(copy, P, _paras('ゼロ。', '一つ目。', '二つ目。', '三つ目。'))
    assert out == 'ゼロ。\n一つ目。\n二つ目。\n三つ目。\n'


def test_a_standing_customer_change_is_not_written_over():
    P = ['一つ目。', '中村さんの二つ目。']
    copy = _paras(*P)
    out, done, left = _write(copy, P, _paras('一つ目。', '二つ目。'), held={'中村さんの二つ目。'})
    assert out == _text(copy) and done == 0 and left == 1
    # taken back (no longer standing): the owner's words go in
    out, done, _ = _write(copy, P, _paras('一つ目。', '二つ目。'))
    assert out == '一つ目。\n二つ目。\n' and done == 1


def test_what_the_customer_changed_comes_in_as_suggestions():
    P = ['今日は大事な話をします。', '二つ目。']
    C = ['今日はとても大事な話をします。', '二つ目。', '中村さんが足した段落。']
    work = _paras('今日は大事な話をします。', '二つ目。')
    W = SH.paragraphs(work)
    found = SH.client_suggestions(P, C, W, [w['text'] for w in W])
    sugs = [s for s, _ in found]
    assert [(s['del'], s['ins'], s['by']) for s in sugs] == [('', 'とても', 'client'), ('', '中村さんが足した段落。', 'client')]
    # laid over the working doc they show where they go, and 承認 writes them
    view, placed = M.overlay(work, sugs)
    assert set(placed) == {s['id'] for s in sugs}
    units = S.outline(view)
    for n, u in enumerate(units): u['n'] = n
    assert {s['by'] for s in S.suggestions_of(units, sugs)} == {'client'}
    toks, end = M.tokens(view, 0, 0, S._chars)
    new_toks, _ = M.plan(toks, M.text_of(toks), M.bmask_of(toks), 'edit', force={sugs[0]['id']: True})
    a, pos, abm, b, bbm, _, ops = M.doc_change(toks, new_toks)
    assert _apply(_text(work), S.replace_requests(pos + [end], a, b, abm, bbm, ops)).startswith('今日はとても大事な話をします。\n')


def test_both_changed_the_same_paragraph():
    P = ['元の文です。']
    C = ['中村さんの文です。']
    work = _paras('みきさんの文です。')
    W = SH.paragraphs(work)
    found = SH.client_suggestions(P, C, W, [w['text'] for w in W])
    assert [(s['del'], s['ins']) for s, _ in found] == [('みきさんの文です。', '中村さんの文です。')]
    assert found[0][1] == ['中村さんの文です。']
