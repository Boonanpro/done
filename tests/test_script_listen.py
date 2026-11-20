"""The script listening screen's text handling (app/services/script_listen.py)."""
import numpy as np

from app.services import script_listen as S


def _para(runs, start=1, style='NORMAL_TEXT'):
    els, idx = [], start
    for text, ts, extra in runs:
        els.append({'startIndex': idx, 'textRun': {'content': text, 'textStyle': ts, **extra}})
        idx += sum(S._units16(c) for c in text)
    return {'paragraph': {'elements': els, 'paragraphStyle': {'namedStyleType': style}}, 'startIndex': start}


def _doc(*paras):
    content, idx = [], 1
    for p in paras:
        runs = p if isinstance(p, list) else [(p, {}, {})]
        style = 'NORMAL_TEXT'
        if isinstance(p, tuple): runs, style = [(p[0], {}, {})], p[1]
        el = _para(runs, idx, style)
        content.append(el)
        idx += sum(S._units16(c) for r in runs for c in r[0])
    return {'body': {'content': content}}


BLUE = {'foregroundColor': {'color': {'rgbColor': {'red': 0.07, 'green': 0.33, 'blue': 0.8}}}}


def test_only_script_sentences_are_spoken():
    doc = _doc(('台本 第1稿\n', 'HEADING_1'), ('◎サムネ\n', 'HEADING_2'), 'A（本命）\n', ('◎タイトル\n', 'HEADING_2'),
               '今までありがとう。\n', ('◎前提と狙い\n', 'HEADING_2'), '狙い：登録してもらう。\n', ('◎台本\n', 'HEADING_2'),
               ('【1】はじめに\n', 'HEADING_2'), ('▼お礼\n', 'HEADING_3'), [('［笑顔で］\n', BLUE, {})],
               '中村です。今日は「大事なお知らせ。本当です。」があります！？\n', '次の段落です。\n')
    units = S.outline(doc)
    says = [u for u in units if u['kind'] == 'say']
    assert [u['speak'] for u in says] == ['中村です。', '今日は「大事なお知らせ。本当です。」があります！？', '次の段落です。']
    # 11/19: one short pause everywhere, no longer stops at paragraphs and sections
    assert [u['gap'] for u in says] == ['s', 's', 's']
    notes = [u['text'] for u in units if u['kind'] == 'note']
    assert 'A（本命）' in notes and '［笑顔で］' in notes and '狙い：登録してもらう。' in notes


def test_blue_notes_inside_a_sentence_are_not_spoken_but_kept_for_editing():
    doc = _doc(('◎台本\n', 'HEADING_2'), [('ここで', {}, {}), ('［画面を出す］', BLUE, {}), ('話します。\n', {}, {})])
    say = [u for u in S.outline(doc) if u['kind'] == 'say'][0]
    assert say['speak'] == 'ここで話します。'
    assert say['text'] == 'ここで［画面を出す］話します。'


def test_suggested_text_is_read_as_accepted_and_locked():
    doc = _doc(('◎台本\n', 'HEADING_2'),
               [('古い', {}, {'suggestedDeletionIds': ['x']}), ('新しい', {}, {'suggestedInsertionIds': ['y']}), ('文です。\n', {}, {})])
    say = [u for u in S.outline(doc) if u['kind'] == 'say'][0]
    assert say['speak'] == '新しい文です。' and say['locked']


def test_edit_touches_only_the_changed_characters():
    old, new = '本当に驚きました。', '本当にびっくりしました。'
    reqs = S.edit_requests(100, old, new)
    doc = list(old)
    for r in reqs:   # apply like the Docs API would, positions are doc indices (start at 100)
        if 'deleteContentRange' in r:
            a, b = r['deleteContentRange']['range']['startIndex'] - 100, r['deleteContentRange']['range']['endIndex'] - 100
            del doc[a:b]
        else:
            i = r['insertText']['location']['index'] - 100
            doc[i:i] = list(r['insertText']['text'])
    assert ''.join(doc) == new
    assert all(r.get('deleteContentRange', {}).get('range', {}).get('startIndex', 103) >= 103 for r in reqs)


def test_edit_positions_count_utf16():
    reqs = S.edit_requests(10, '😀あ', '😀い')
    assert reqs[0]['deleteContentRange']['range'] == {'startIndex': 12, 'endIndex': 13}


def test_trim_cuts_head_and_tail_silence():
    rate = 1000
    x = np.concatenate([np.zeros(500), np.full(300, 8000), np.zeros(700)]).astype('int16')
    y = S._trim(x, rate)
    assert 300 <= len(y) <= 300 + 2 * 30 + 20


def test_new_text_takes_the_boldness_of_what_it_replaces():
    old, new = '強く言います。', '強く言わせてください。'
    reqs = S.edit_requests(1, old, new, '1100000')
    styles = [r['updateTextStyle'] for r in reqs if 'updateTextStyle' in r]
    assert styles and all(st['textStyle']['bold'] is False for st in styles)


def test_a_star_heading_inside_the_script_stays_in_the_script():
    doc = _doc(('◎前提と狙い\n', 'HEADING_2'), '狙い：予約。\n', ('◎台本\n', 'HEADING_2'), ('▼追加特典\n', 'HEADING_3'),
               '振り切りました。\n', ('◎追加特典①ブーストセット\n', 'HEADING_3'), '1つ目はこれです。\n')
    units = S.outline(doc)
    star = next(u for u in units if u['text'].startswith('◎追加特典'))
    assert star['level'] == 3 and star['read']
    said = [u for u in units if u['kind'] == 'say']
    assert [u['speak'] for u in said] == ['振り切りました。', '1つ目はこれです。']
    assert said[1]['section'].startswith('◎追加特典') and said[0]['gap'] == 's'


def test_suggestions_show_where_they_are_and_are_listed_once():
    doc = _doc(('◎台本\n', 'HEADING_2'),
               [('古い', {}, {'suggestedDeletionIds': ['x']}), ('新しい', {}, {'suggestedInsertionIds': ['x']}), ('文です。', {}, {}),
                ('消える文です。', {}, {'suggestedDeletionIds': ['y']}), ('残る文です。\n', {}, {})],
               [('全部消える段落です。\n', {}, {'suggestedDeletionIds': ['z']})])
    units = S.outline(doc)
    for n, u in enumerate(units): u['n'] = n
    says = [u for u in units if u['kind'] == 'say']
    assert [u['speak'] for u in says] == ['新しい文です。', '残る文です。']
    assert says[0]['segs'][:2] == [{'t': '古い', 'del': 'x'}, {'t': '新しい', 'ins': 'x'}]
    # the deleted sentence between two kept ones is drawn with the one after it, struck through
    assert {'t': '消える文です。', 'del': 'y'} in says[1]['segs'] and says[1]['locked']
    gone = [u for u in units if u['kind'] == 'gone']
    assert gone and gone[0]['segs'] == [{'t': '全部消える段落です。', 'del': 'z'}]
    sug = {s['id']: s for s in S.suggestions_of(units)}
    assert sug['x']['ins'] == '新しい' and sug['x']['del'] == '古い' and sug['z']['del'] == '全部消える段落です。'


def test_top_part_keeps_pictures():
    doc = _doc(('◎サムネ\n', 'HEADING_2'), '絵の下の文\n', ('◎台本\n', 'HEADING_2'), '本文です。\n')
    doc['body']['content'][1]['paragraph']['elements'].insert(0, {'startIndex': 1, 'inlineObjectElement': {'inlineObjectId': 'i.0'}})
    doc['inlineObjects'] = {'i.0': {'inlineObjectProperties': {'embeddedObject': {'imageProperties': {'contentUri': 'https://x/img'}}}}}
    units = S.outline(doc)
    assert {'kind': 'image', 'src': 'https://x/img'} in units


def _apply(text, reqs, base=1):
    """Apply delete / insert requests to a string the way the Docs API does (indices from ``base``)."""
    doc = list(text)
    for r in reqs:
        if 'deleteContentRange' in r:
            rg = r['deleteContentRange']['range']; del doc[rg['startIndex'] - base:rg['endIndex'] - base]
        elif 'insertText' in r:
            i = r['insertText']['location']['index'] - base; doc[i:i] = list(r['insertText']['text'])
    return ''.join(doc)


def test_accept_and_reject_write_what_docs_would():
    # 「で」 suggested out, 「なら」 suggested in: 「一括でなら36万円」 as stored
    text = '一括でなら36万円'
    runs = [(3, 4, 'del', 'で', {}, 'NORMAL_TEXT', None), (4, 6, 'ins', 'なら', {'bold': True}, 'NORMAL_TEXT', None)]
    assert _apply(text, S.decide_requests(runs, accept=True)[0]) == '一括なら36万円'
    assert _apply(text, S.decide_requests(runs, accept=False)[0]) == '一括で36万円'
    style = S.decide_requests(runs, accept=True)[1][0]['updateTextStyle']
    # 「で」 (index 3) is gone, so 「なら」 now starts at 3
    assert style['range'] == {'startIndex': 3, 'endIndex': 5} and style['textStyle'] == {'bold': True} and style['fields'] == '*'
    style = S.decide_requests(runs, accept=False)[1][0]['updateTextStyle']
    assert style['range'] == {'startIndex': 3, 'endIndex': 4}


def test_accepted_new_paragraph_keeps_both_paragraph_styles():
    runs = [(10, 15, 'ins', '見出し\n', {}, 'HEADING_3', 'NORMAL_TEXT')]
    reqs = S.decide_requests(runs, accept=True)[1]
    styles = [r['updateParagraphStyle'] for r in reqs if 'updateParagraphStyle' in r]
    assert [x['paragraphStyle']['namedStyleType'] for x in styles] == ['HEADING_3', 'NORMAL_TEXT']


def test_emptying_a_sentence_deletes_it_or_its_paragraph():
    doc = _doc(('◎台本\n', 'HEADING_2'), '一つ目です。 二つ目です。\n', 'ひとりの段落です。\n', '最後です。\n')
    # the last element needs endIndex like the Docs API gives
    for el in doc['body']['content']:
        p = el['paragraph']; n = sum(S._units16(c) for e in p['elements'] for c in e['textRun']['content'])
        el['endIndex'] = el['startIndex'] + n
    says = [u for u in S.outline(doc) if u['kind'] == 'say']
    first, alone = says[0], says[2]
    r = S.delete_requests(doc, first)[0]['deleteContentRange']['range']
    assert r['endIndex'] - r['startIndex'] == len('一つ目です。 ')          # the space after it goes too
    r = S.delete_requests(doc, alone)[0]['deleteContentRange']['range']
    para = doc['body']['content'][alone['para']]
    assert (r['startIndex'], r['endIndex']) == (para['startIndex'], para['endIndex'])   # with its newline


def _ends(doc):
    for el in doc['body']['content']:
        p = el['paragraph']; n = sum(S._units16(c) for e in p['elements'] for c in e['textRun']['content'])
        el['endIndex'] = el['startIndex'] + n
    return doc


def test_every_paragraph_shows_exactly_the_doc_text():
    # The screen is one editing surface (11/19): what it draws for each paragraph must be the doc's own text, so a
    # change can be sent as「these paragraphs read X, now read Y」.
    doc = _ends(_doc(('台本 第1稿\n', 'TITLE'), ('◎サムネ\n', 'HEADING_2'), 'A（本命）\n', '\n', ('◎台本\n', 'HEADING_2'),
                     ('【1】はじめに\n', 'HEADING_2'), [('［笑顔で］\n', BLUE, {})],
                     [('中村です。  今日は', {}, {}), ('古い', {}, {'suggestedDeletionIds': ['x']}),
                      ('新しい', {}, {'suggestedInsertionIds': ['y']}), ('話です。 \n', {'bold': True}, {})],
                     '　\n', '最後です。\n'))
    units = S.outline(doc)
    shown = {}
    for u in units:
        if u['kind'] == 'image': continue
        assert 'para' in u and 'segs' in u, u
        shown[u['para']] = shown.get(u['para'], '') + ''.join(s['t'] for s in u['segs'])
    assert sorted(shown) == list(range(len(doc['body']['content'])))
    for pi, text in shown.items():
        assert S._para_span(doc, pi, pi)[0] == text


def test_typing_next_to_a_suggestion_is_allowed_but_not_inside_it():
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'),
                     [('前の', {}, {}), ('古い', {}, {'suggestedDeletionIds': ['x']}), ('文です。\n', {}, {})]))
    old, pos, _, locked = S._para_span(doc, 1, 1)
    assert old == '前の古い文です。'
    assert not S.touches_suggestion(old, '前の古い文でした。', locked)
    assert not S.touches_suggestion(old, 'すごく前の古い文です。', locked)
    assert S.touches_suggestion(old, '前の古文です。', locked)
    assert S.touches_suggestion(old, '前の古xい文です。', locked)


def test_enter_and_joining_paragraphs_write_newlines():
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), '一つ目です。二つ目です。\n', '三つ目です。\n'))
    old, pos, bm, _ = S._para_span(doc, 1, 2)
    assert old == '一つ目です。二つ目です。\n三つ目です。'
    body = '◎台本\n一つ目です。二つ目です。\n三つ目です。\n'
    split = S.replace_requests(pos, old, '一つ目です。\n二つ目です。\n三つ目です。', bm, '0' * 20)
    assert _apply(body, split) == '◎台本\n一つ目です。\n二つ目です。\n三つ目です。\n'
    joined = S.replace_requests(pos, old, '一つ目です。二つ目です。三つ目です。', bm, '0' * 20)
    assert _apply(body, joined) == '◎台本\n一つ目です。二つ目です。三つ目です。\n'


def test_bold_is_written_only_where_the_screen_changed_it():
    doc = _ends(_doc(('◎台本\n', 'HEADING_2'), '大事な話です。\n'))
    old, pos, bm, _ = S._para_span(doc, 1, 1)
    reqs = S.replace_requests(pos, old, old, '0' * 7, '0011000')
    st = [r['updateTextStyle'] for r in reqs]
    assert len(st) == 1 and st[0]['textStyle'] == {'bold': True}
    assert (st[0]['range']['startIndex'] - pos[0], st[0]['range']['endIndex'] - pos[0]) == (2, 4)


def test_anchor_note_names_the_suggestion_a_comment_is_about(tmp_path, monkeypatch):
    """11/20: a comment written on a suggestion's card reaches Dan with that suggestion, and the rule to replace
    Dan's own old suggestion instead of piling a second one on it."""
    from app.services import script_listen as S
    monkeypatch.setattr(S, 'ANCHORS', tmp_path / 'anchors.json')
    monkeypatch.setattr(S, 'STATE', tmp_path)
    S._remember_anchor('c1', start=10, sentence='一括なら36万円です。', doc_id='d',
                       suggestion=S._clean_suggestion({'id': 's1', 'ins': 'なら', 'del': 'で'}))
    S._remember_anchor('c2', start=20, sentence='別の文。', doc_id='d')
    note = S.anchor_note(['c1', 'c2'])
    assert '文「一括なら36万円です。」' in note and '文「別の文。」' in note
    assert 'c1: 提案（置き換え「で」→「なら」）' in note
    assert 'c2: 提案' not in note
    assert '却下してから' in note
    # a reply on the card of Dan's new suggestion moves the thread on to it, keeping where it was written
    S._remember_anchor('c1', doc_id='d', suggestion=S._clean_suggestion({'id': 's2', 'ins': 'の場合は', 'del': ''}))
    a = S._anchors()['c1']
    assert a['suggestion']['id'] == 's2' and a['sentence'] == '一括なら36万円です。'
    assert '提案（足す「の場合は」）' in S.anchor_note(['c1'])
    assert S.anchor_note(['c2']).count('提案') == 0
