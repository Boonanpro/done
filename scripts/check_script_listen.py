"""台本を聞く画面（/script-listen）を、本人の使い方どおりに音なしのブラウザで通して確かめる。

  python scripts/check_script_listen.py --base http://localhost:3002 --doc <聞くだけの台本> [--edit-doc <直してよい写し>] [--phone] [--comment]

確かめること（結果は .data/script-listen-check/<時刻>.json と画面の写真）:
  1. 聞く → 文が順に進む。文と文のつなぎ目の無音（秒。前の文の声が終わってから次の文が鳴り出すまで）。段落や段の切れ目でも
     同じ長さか（11/19 本人「全部一気に再生できるように」）。
  2. 3倍 → 鳴っている音の速さが3倍で、声の高さを保つ設定のまま。
  3. 直す（--edit-doc の時だけ。本人の台本は直さない）: 文を押して、その場で打ち（四角い入力欄は無い）、Enter →
     ドキュメントにその文が入り、画面のその文から鳴り直す。スマホ（--phone）は鳴っている文をもう一度押して打つ。
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
            target = says[3]
            span = page.locator(f'span[data-n="{target["n"]}"]')
            span.scroll_into_view_if_needed()
            tap(span)
            if a.phone: tap(span)      # the second tap on the sentence being read lets the owner type
            span.evaluate("""el => { el.focus(); const r = document.createRange(); r.selectNodeContents(el); r.collapse(false);
                                     const s = getSelection(); s.removeAllRanges(); s.addRange(r); }""")
            page.keyboard.press('ArrowLeft')               # before the closing 。
            page.keyboard.insert_text('よ')
            new = target['text'][:-1] + 'よ' + target['text'][-1]
            result['typing_paused_player'] = page.get_by_role('button', name='聞く', exact=True).is_visible()
            page.evaluate('window.__log = []')
            t1 = time.time()
            page.keyboard.press('Enter')
            page.wait_for_function("window.__log.some(x=>x.t1)", timeout=60000)
            result['edit'] = {'old': target['text'], 'new': new, 'sound_after_s': round(time.time() - t1, 1),
                              'highlighted': page.locator('span[data-n].bg-amber-200\\/80').first.inner_text(),
                              'in_doc': any(u['text'] == new for u in S.read(a.edit_doc)['units'] if u['kind'] == 'say'),
                              'no_text_box': page.locator('textarea').count() == 0}
            page.screenshot(path=str(out_dir / f'{stamp}-edited.png'))
            page.get_by_role('button', name='止める', exact=True).click()

            # 3b. a click to listen leaves the caret in the sentence: Space must pause, not type into the doc
            if not a.phone:
                quiet = says[5]
                sp = page.locator(f'span[data-n="{quiet["n"]}"]')
                sp.scroll_into_view_if_needed(); sp.click()
                page.wait_for_timeout(1500)
                page.keyboard.press('Space')
                page.wait_for_timeout(800)
                paused = page.get_by_role('button', name='聞く', exact=True).is_visible()
                page.locator('body').click(position={'x': 5, 'y': 300})      # move focus away (a blur would save a change)
                page.wait_for_timeout(2500)
                still = any(u['text'] == quiet['text'] for u in S.read(a.edit_doc)['units'] if u['kind'] == 'say')
                result['space_after_click'] = {'paused': paused, 'doc_unchanged': still}

            # 4. someone else changes the doc
            other = says[6]
            mark = f'（ドキュメント側の直し{stamp[-6:]}）'
            changed = other['text'][:-1] + mark + '。'
            S.edit(a.edit_doc, other['text'], changed, None, other['start'])
            t2 = time.time()
            page.locator(f'span[data-n]:has-text("{mark}")').first.wait_for(timeout=40000)
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
                page.locator('button.fixed:has-text("コメント")').click()
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
    path = out_dir / f'{stamp}.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps(result, ensure_ascii=False, indent=1))
    print('記録:', path)


if __name__ == '__main__':
    main()
