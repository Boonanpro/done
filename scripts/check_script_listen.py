"""台本を聞く画面（/script-listen）を、本人の使い方どおりに音なしのブラウザで通して確かめる。

  python scripts/check_script_listen.py --base http://localhost:3002 --doc <聞くだけの台本> [--edit-doc <直してよい写し>] [--phone] [--comment]

確かめること（結果は .data/script-listen-check/<時刻>.json と画面の写真）:
  1. 聞く → 文が順に進む。文と文のつなぎ目の無音（秒。前の文の声が終わってから次の文が鳴り出すまで）。段落や段の切れ目でも
     同じ長さか（11/19 本人「全部一気に再生できるように」）。
  2. 3倍 → 鳴っている音の速さが3倍で、声の高さを保つ設定のまま。
  3. 直す（--edit-doc の時だけ。本人の台本は直さない）: 本文は1枚の編集面で、押した文に枠が出ない。その場で打つと、
     打つのを止めた後に自動でドキュメントに入る。Ctrl+Z / Ctrl+Shift+Z、Ctrl+B（太字）、Enter（段落を分ける）がドキュメントに入る。
     段落をまたいで選べて、右の余白にコメントの印が出る。スマホ（--phone）は鳴っている文をもう一度押して打つ。
  4. ドキュメントが別に直された時（--edit-doc の時だけ）: 25秒以内に画面が読み直して新しい文を出す。
  5. 提案（--edit-doc に提案がある時だけ）: 提案の札の「却下」→ ドキュメントからその提案が消える。
  6. コメント（--comment の時だけ。ダンが返事をしに動くので、写しに対してだけ使う）: 言葉を選ぶ →「コメント」→ 送る →
     ドキュメントのコメントに入り、画面の札に出る。
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Every clip ends with 0.16 s of silence plus 0.03 s kept after the voice (app/services/script_listen.py GAPS / _trim).
TAIL = 0.19
HEAD = 0.03
HOOK = """
window.__log = []; window.__last = null;
const _play = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function () {
  const el = this, prev = window.__last;
  const rec = {t0: performance.now(), rate: el.playbackRate, prevC: prev && prev !== el ? prev.currentTime : null,
               prevD: prev && prev !== el ? prev.duration : null};
  el.addEventListener('playing', () => { rec.t1 = performance.now(); rec.pitch = el.preservesPitch; rec.rate = el.playbackRate; }, {once: true});
  window.__log.push(rec);
  window.__last = el;
  return _play.call(this);
};
"""


def token():
    from app.services.auth_service import create_access_token
    from app.config import settings
    uid = getattr(settings, 'OWNER_USER_ID', '') or 'script-listen-check'
    return create_access_token(uid, 'check@dan.local')


def silences(log):
    """Seconds of silence heard at each join: what was left of the old clip's voice-free tail when the next one was
    started, plus the time the next one took to sound, plus its head."""
    out = []
    for r in log:
        if r.get('prevC') is None or not r.get('t1') or not r.get('prevD'): continue
        rate = r['rate'] or 1
        out.append(round((r['t1'] - r['t0']) / 1000 + (r['prevC'] - (r['prevD'] - TAIL)) / rate + HEAD / rate, 3))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://localhost:3002')
    ap.add_argument('--doc', required=True)
    ap.add_argument('--edit-doc')
    ap.add_argument('--phone', action='store_true')
    ap.add_argument('--comment', action='store_true')
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    out_dir = ROOT / '.data' / 'script-listen-check'
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    result = {'doc': a.doc, 'phone': a.phone}
    tok = token()
    try:
        run(a, result, out_dir, stamp, tok, sync_playwright)
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {str(exc)[:300]}'
        write(result, out_dir, stamp)
        raise
    write(result, out_dir, stamp)


def run(a, result, out_dir, stamp, tok, sync_playwright):
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=['--mute-audio', '--autoplay-policy=no-user-gesture-required'])
        ctx = b.new_context(viewport={'width': 412, 'height': 900} if a.phone else {'width': 1440, 'height': 900},
                            is_mobile=a.phone, has_touch=a.phone)
        ctx.add_init_script(f"localStorage.setItem('done-token', {json.dumps(tok)}); localStorage.setItem('script-listen-rate','1');"
                            f"localStorage.removeItem('script-listen-pos-{a.doc}');" + HOOK)
        page = ctx.new_page()
        tap = (lambda loc: loc.tap()) if a.phone else (lambda loc: loc.click())

        # 1. listen
        page.goto(f'{a.base}/script-listen?doc={a.doc}')
        page.get_by_role('button', name='聞く', exact=True).wait_for(timeout=60000)
        page.screenshot(path=str(out_dir / f'{stamp}-open.png'))
        t0 = time.time()
        page.get_by_role('button', name='聞く', exact=True).click()
        page.wait_for_function("window.__log.filter(x=>x.t1).length>=8", timeout=120000)
        result['silence_s_1x'] = silences(page.evaluate('window.__log'))
        result['progress_1x'] = page.locator('text=/\\d+ \\/ \\d+文/').inner_text()
        result['listened_s'] = round(time.time() - t0, 1)
        page.screenshot(path=str(out_dir / f'{stamp}-listening.png'))

        # 2. 3x
        page.get_by_role('button', name='3倍', exact=True).click()
        page.evaluate('window.__log = []')
        page.wait_for_function("window.__log.filter(x=>x.t1).length>=4", timeout=90000)
        log = page.evaluate('window.__log')
        st = page.evaluate('({rate: window.__last.playbackRate, pitch: window.__last.preservesPitch, paused: window.__last.paused})')
        result['at_3x'] = {'now': st, 'pitch_kept': all(x.get('pitch') for x in log if x.get('t1')), 'silence_s': silences(log)}
        page.get_by_role('button', name='止める', exact=True).click()

        if a.edit_doc:
            from app.services import script_listen as S
            S.watch_soon = lambda doc_id: None
            page.goto(f'{a.base}/script-listen?doc={a.edit_doc}')
            page.get_by_role('button', name='聞く', exact=True).wait_for(timeout=60000)
            says = [u for u in S.read(a.edit_doc)['units'] if u['kind'] == 'say' and not u['locked']]
            doc_says = lambda: [u['text'] for u in S.read(a.edit_doc)['units'] if u['kind'] == 'say']

            def wait_doc(pred, timeout=25):
                end = time.time() + timeout
                while time.time() < end:
                    if pred(): return round(timeout - (end - time.time()), 1)
                    time.sleep(1)
                return None

            def caret_end(n):
                page.locator(f'span[data-n="{n}"]').first.evaluate("""el => { const r = document.createRange(); r.selectNodeContents(el); r.collapse(false);
                                   const s = getSelection(); s.removeAllRanges(); s.addRange(r); }""")

            # 3a. one surface, no frame round a sentence
            target = says[3]
            span = page.locator(f'span[data-n="{target["n"]}"]').first
            span.scroll_into_view_if_needed()
            tap(span)
            if a.phone: page.wait_for_timeout(300); tap(span)      # the second tap on the sentence being read lets the owner type
            page.wait_for_timeout(300)
            look = span.evaluate("""el => { const c = getComputedStyle(el); return {outline: c.outlineStyle, shadow: c.boxShadow,
                                     border: c.borderTopWidth, editable_parts: document.querySelectorAll('[contenteditable=true]').length,
                                     focus_in_text: document.activeElement === el.closest('[data-testid=script-editor]')}; }""")
            result['surface'] = {**look, 'no_frame': look['outline'] == 'none' and look['shadow'] == 'none' and look['border'] == '0px'}
            page.screenshot(path=str(out_dir / f'{stamp}-clicked.png'))

            # 3b. type in place; it reaches the doc by itself after a pause
            caret_end(target['n'])
            page.keyboard.press('ArrowLeft')               # before the closing 。
            page.keyboard.insert_text('よ')
            new = target['text'][:-1] + 'よ' + target['text'][-1]
            result['typing_paused_player'] = page.get_by_role('button', name='聞く', exact=True).is_visible()
            result['no_band_while_typing'] = page.locator('[data-testid=script-editor] [data-on]').count() == 0
            page.screenshot(path=str(out_dir / f'{stamp}-typing.png'))
            result['typed'] = {'old': target['text'], 'new': new, 'in_doc_after_s': wait_doc(lambda: new in doc_says())}

            # 3c. Ctrl+Z takes it back, in the doc too; Ctrl+Shift+Z puts it again
            page.keyboard.press('Control+z')
            back = wait_doc(lambda: target['text'] in doc_says() and new not in doc_says())
            page.keyboard.press('Control+Shift+z')
            again = wait_doc(lambda: new in doc_says())
            page.wait_for_timeout(14000)                 # the screen reads the doc again while idle; undo must survive it
            page.keyboard.press('Control+z')
            back2 = wait_doc(lambda: target['text'] in doc_says() and new not in doc_says())
            result['undo'] = {'undone_in_doc_s': back, 'redone_in_doc_s': again, 'undone_after_idle_s': back2}

            # 3d. Ctrl+B makes the selected words bold in the doc
            bold_t = says[4]
            word = bold_t['text'][:4]
            page.locator(f'span[data-n="{bold_t["n"]}"]').first.evaluate("""el => { const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); const t = w.nextNode();
                    const r = document.createRange(); r.setStart(t, 0); r.setEnd(t, 4); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }""")
            page.keyboard.press('Control+b')

            def bold_in_doc():
                u = next((x for x in S.read(a.edit_doc)['units'] if x['kind'] == 'say' and x['start'] == bold_t['start']), None)
                return u and ''.join(sg['t'] for sg in u['segs'] if sg.get('b')).strip() == word
            result['bold'] = {'word': word, 'in_doc_s': wait_doc(bold_in_doc)}
            page.keyboard.press('Control+z')
            result['bold']['undone_s'] = wait_doc(lambda: not bold_in_doc())

            # 3e. Enter splits the paragraph in the doc; Ctrl+Z joins it again
            para_of = {}
            for u in says: para_of.setdefault(u['para'], []).append(u)
            pair = next((v for v in para_of.values() if len(v) >= 2), None)
            if pair:
                first, second = pair[0], pair[1]
                n_paras = lambda: len(S.fetch(a.edit_doc)['body']['content'])
                before_p = n_paras()
                page.locator(f'span[data-n="{first["n"]}"]').first.scroll_into_view_if_needed()
                caret_end(first['n'])
                page.keyboard.press('Enter')
                split = wait_doc(lambda: n_paras() == before_p + 1)
                page.screenshot(path=str(out_dir / f'{stamp}-enter.png'))
                page.keyboard.press('Control+z')
                joined = wait_doc(lambda: n_paras() == before_p)
                result['enter'] = {'split_in_doc_s': split, 'joined_back_s': joined}

            # 3e2. typing through an IME (how the owner types Japanese) lands once; Ctrl+Z takes it back
            ime_t = says[7]
            page.locator(f'span[data-n="{ime_t["n"]}"]').first.scroll_into_view_if_needed()
            caret_end(ime_t['n'])
            page.keyboard.press('ArrowLeft')
            cdp = page.context.new_cdp_session(page)
            cdp.send('Input.imeSetComposition', {'text': 'てすと', 'selectionStart': 3, 'selectionEnd': 3})
            page.wait_for_timeout(300)
            cdp.send('Input.imeSetComposition', {'text': 'テスト', 'selectionStart': 3, 'selectionEnd': 3})
            page.wait_for_timeout(300)
            cdp.send('Input.insertText', {'text': 'テスト'})
            ime_new = ime_t['text'][:-1] + 'テスト' + ime_t['text'][-1]
            got = wait_doc(lambda: ime_new in doc_says())
            page.keyboard.press('Control+z')
            gone = wait_doc(lambda: ime_t['text'] in doc_says() and ime_new not in doc_says())
            result['ime'] = {'in_doc_once_s': got, 'undone_s': gone}

            # 3e3. pasting two lines makes two paragraphs
            n_paras = lambda: len(S.fetch(a.edit_doc)['body']['content'])
            before_p = n_paras()
            caret_end(ime_t['n'])
            page.locator('[data-testid=script-editor]').evaluate("el => { const dt = new DataTransfer(); dt.setData('text/plain', '貼った一行目です。\\n貼った二行目です。');"
                " el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true})); }")
            pasted = wait_doc(lambda: n_paras() == before_p + 1 and any('貼った二行目です。' == t for t in doc_says()))
            page.keyboard.press('Control+z')
            unpasted = wait_doc(lambda: n_paras() == before_p and not any('貼った' in t for t in doc_says()))
            result['paste'] = {'two_paragraphs_s': pasted, 'undone_s': unpasted}

            # 3f. a selection across two paragraphs, and the comment mark beside it
            if not a.phone:
                p1, p2 = says[3], next(u for u in says if u['para'] != says[3]['para'] and u['n'] > says[3]['n'])
                e1 = page.locator(f'span[data-n="{p1["n"]}"]').first
                e2 = page.locator(f'span[data-n="{p2["n"]}"]').first
                e1.scroll_into_view_if_needed()
                b1, b2 = e1.bounding_box(), e2.bounding_box()
                page.mouse.move(b1['x'] + 3, b1['y'] + b1['height'] / 2)
                page.mouse.down()
                page.mouse.move(b2['x'] + b2['width'] - 3, b2['y'] + b2['height'] / 2, steps=12)
                page.mouse.up()
                page.wait_for_timeout(400)
                sel = page.evaluate('getSelection().toString()')
                mark = page.get_by_role('button', name='コメントを追加')
                result['cross_select'] = {'has_both': p1['text'][:5] in sel and p2['text'][:5] in sel and '\n' in sel,
                                          'comment_mark': mark.is_visible(),
                                          'mark_in_margin': mark.is_visible() and mark.bounding_box()['x'] > b2['x'] + 300}
                page.screenshot(path=str(out_dir / f'{stamp}-select.png'))
                page.locator('body').click(position={'x': 5, 'y': 300})
                page.wait_for_timeout(2500)

            # 3g. after typing, a click on a sentence writes it, reads the doc again and plays from there
            if not a.phone:
                quiet = says[5]
                sp = page.locator(f'span[data-n="{quiet["n"]}"]').first
                sp.scroll_into_view_if_needed(); sp.click()
                page.wait_for_timeout(1500)
                page.keyboard.press('Space')
                page.wait_for_timeout(800)
                paused = page.get_by_role('button', name='聞く', exact=True).is_visible()
                page.locator('body').click(position={'x': 5, 'y': 300})
                page.wait_for_timeout(2500)
                result['space_after_click'] = {'paused': paused, 'doc_unchanged': quiet['text'] in doc_says()}
                page.evaluate('window.__log = []')
                t1 = time.time()
                sp.click()
                page.wait_for_function("window.__log.some(x=>x.t1)", timeout=60000)
                result['click_plays_s'] = round(time.time() - t1, 1)
                page.get_by_role('button', name='止める', exact=True).click()

            # 4. someone else changes the doc
            other = says[6]
            mark = f'（ドキュメント側の直し{stamp[-6:]}）'
            changed = other['text'][:-1] + mark + '。'
            S.edit(a.edit_doc, other['text'], changed, None, other['start'])
            t2 = time.time()
            page.locator(f'[data-testid=script-editor] :text("{mark}")').first.wait_for(timeout=40000)
            result['doc_side_edit_seen_s'] = round(time.time() - t2, 1)

            # 5. a suggestion: reject it on the screen
            sug = S.read(a.edit_doc)['suggestions']
            if sug:
                s0 = sug[0]
                if a.phone:
                    seg = page.locator('span.line-through, span.underline').first
                    seg.scroll_into_view_if_needed(); tap(seg)
                    page.get_by_role('button', name='却下').first.wait_for(timeout=10000)
                    page.screenshot(path=str(out_dir / f'{stamp}-suggestion-sheet.png'))
                card_btn = page.get_by_role('button', name='却下').first
                card_btn.scroll_into_view_if_needed()
                card_btn.click()
                page.wait_for_timeout(4000)
                left = {x['id'] for x in S.read(a.edit_doc)['suggestions']}
                result['suggestion'] = {'id': s0['id'], 'gone_from_doc': s0['id'] not in left}

            # 6. a comment
            if a.comment:
                pick = says[8]
                sp = page.locator(f'span[data-n="{pick["n"]}"]')
                sp.scroll_into_view_if_needed()
                before = page.evaluate("document.querySelector('.overflow-y-auto').scrollTop")
                sp.evaluate("""el => { const r = document.createRange(); r.setStart(el.firstChild, 0); r.setEnd(el.firstChild, Math.min(6, el.firstChild.length));
                                       const s = getSelection(); s.removeAllRanges(); s.addRange(r); }""")
                page.get_by_role('button', name='コメントを追加').click()
                page.wait_for_timeout(400)
                after = page.evaluate("document.querySelector('.overflow-y-auto').scrollTop")
                text = f'【確かめ{stamp[-6:]}】この言い方、耳で聞いて分かりやすい？（答えだけで、本文は直さないで）'
                page.locator('textarea').last.fill(text)
                page.get_by_role('button', name='送る').last.click()
                page.locator(f'text={text[:12]}').first.wait_for(timeout=20000)
                threads = S.comments(a.edit_doc)['threads']
                hit = [t for t in threads if t['messages'] and t['messages'][0].get('text') == text]
                result['comment'] = {'in_doc': bool(hit), 'quote': hit[0]['quote'] if hit else None,
                                     'page_stayed': abs(after - before) < 200, 'working': hit[0]['working'] if hit else None}
                page.screenshot(path=str(out_dir / f'{stamp}-comment.png'))
        b.close()


def write(result, out_dir, stamp):
    path = out_dir / f'{stamp}.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps(result, ensure_ascii=False, indent=1))
    print('記録:', path)


if __name__ == '__main__':
    main()
