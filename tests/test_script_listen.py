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
    assert [u['gap'] for u in says] == ['s', 'p', 'h']
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
    assert said[1]['section'].startswith('◎追加特典') and said[0]['gap'] == 'h'
