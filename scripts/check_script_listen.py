"""台本を聞く画面（/script-listen）を、本人の使い方どおりに音なしのブラウザで通して確かめる。

  python scripts/check_script_listen.py --base http://localhost:3002 --doc <聞くだけの台本> [--edit-doc <直してよい写し>] [--phone]

確かめること（結果は .data/script-listen-check/<時刻>.json と画面の写真）:
  1. 聞く → 文が順に進む。文と文のつなぎ目で、前の文が終わってから次の文が鳴り出すまでの待ち（ミリ秒）。
  2. 3倍 → 鳴っている音の速さが3倍で、声の高さを保つ設定のまま。
  3. 直す（--edit-doc の時だけ。本人の台本は直さない）: 文を押して書き換え →「直して聞く」→ ドキュメントにその文が入り、
     画面のその文から鳴り直す。
  4. ドキュメントが別に直された時（--edit-doc の時だけ）: 25秒以内に画面が読み直して新しい文を出す。
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HOOK = """
window.__log = [];
const _play = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function () {
  const el = this;
  if (!el.__hooked) {
    el.__hooked = 1;
    el.addEventListener('ended', () => window.__log.push({e: 'end', t: performance.now()}));
    el.addEventListener('playing', () => window.__log.push({e: 'playing', t: performance.now(), rate: el.playbackRate, pitch: el.preservesPitch, muted: el.muted}));
  }
  window.__last = el;
  return _play.call(this);
};
"""


def token():
    from app.services.auth_service import create_access_token
    from app.config import settings
    uid = getattr(settings, 'OWNER_USER_ID', '') or 'script-listen-check'
    return create_access_token(uid, 'check@dan.local')


def gaps(log):
    out, last_end = [], None
    for x in log:
        if x['e'] == 'end': last_end = x['t']
        elif x['e'] == 'playing' and last_end is not None:
            out.append(round(x['t'] - last_end)); last_end = None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://localhost:3002')
    ap.add_argument('--doc', required=True)
    ap.add_argument('--edit-doc')
    ap.add_argument('--phone', action='store_true')
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    out_dir = ROOT / '.data' / 'script-listen-check'
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    result = {'doc': a.doc, 'phone': a.phone}
    tok = token()
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=['--mute-audio', '--autoplay-policy=no-user-gesture-required'])
        ctx = b.new_context(viewport={'width': 412, 'height': 900} if a.phone else {'width': 1280, 'height': 900},
                            is_mobile=a.phone, has_touch=a.phone)
        ctx.add_init_script(f"localStorage.setItem('done-token', {json.dumps(tok)}); localStorage.setItem('script-listen-rate','1');"
                            f"localStorage.removeItem('script-listen-pos-{a.doc}');" + HOOK)
        page = ctx.new_page()

        # 1. listen
        page.goto(f'{a.base}/script-listen?doc={a.doc}')
        page.get_by_role('button', name='聞く', exact=True).wait_for(timeout=60000)
        t0 = time.time()
        page.get_by_role('button', name='聞く', exact=True).click()
        page.wait_for_function("window.__log.filter(x=>x.e==='playing').length>=4", timeout=90000)
        log = page.evaluate('window.__log')
        result['gaps_ms_1x'] = gaps(log)
        result['progress_1x'] = page.locator('text=/\\d+ \\/ \\d+文/').inner_text()
        result['listened_s'] = round(time.time() - t0, 1)
        page.screenshot(path=str(out_dir / f'{stamp}-listening.png'))

        # 2. 3x
        page.get_by_role('button', name='3倍', exact=True).click()
        page.evaluate('window.__log = []')
        page.wait_for_function("window.__log.filter(x=>x.e==='playing').length>=3", timeout=90000)
        log = page.evaluate('window.__log')
        st = page.evaluate('({rate: window.__last.playbackRate, pitch: window.__last.preservesPitch, paused: window.__last.paused})')
        result['at_3x'] = {'now': st, 'playing_events': [{'rate': x['rate'], 'pitch': x['pitch']} for x in log if x['e'] == 'playing'],
                           'gaps_ms': gaps(log)}
        page.get_by_role('button', name='止める', exact=True).click()

        if a.edit_doc:
            from app.services import script_listen as S
            page.goto(f'{a.base}/script-listen?doc={a.edit_doc}')
            page.get_by_role('button', name='聞く', exact=True).wait_for(timeout=60000)
            says = [u for u in S.read(a.edit_doc)['units'] if u['kind'] == 'say']
            target = says[3]
            new = target['text'].replace('、', '、本当に', 1) if '、' in target['text'] else target['text'][:-1] + 'よ。'
            page.get_by_role('button', name=target['text'][:40]).first.click()
            page.locator('textarea').fill(new)
            page.evaluate('window.__log = []')
            t1 = time.time()
            page.get_by_role('button', name='直して聞く', exact=True).click()
            page.wait_for_function("window.__log.some(x=>x.e==='playing')", timeout=60000)
            result['edit'] = {'old': target['text'], 'new': new, 'sound_after_s': round(time.time() - t1, 1),
                              'highlighted': page.locator('.bg-amber-200\\/80').first.inner_text(),
                              'in_doc': any(u['text'] == new for u in S.read(a.edit_doc)['units'] if u['kind'] == 'say')}
            page.screenshot(path=str(out_dir / f'{stamp}-edited.png'))
            page.get_by_role('button', name='止める', exact=True).click()

            # 4. someone else changes the doc
            other = says[6]
            mark = f'（ドキュメント側の直し{stamp[-6:]}）'
            changed = other['text'][:-1] + mark + '。'
            S.edit(a.edit_doc, other['text'], changed, None, other['start'])
            t2 = time.time()
            page.get_by_role('button', name=mark).first.wait_for(timeout=40000)
            result['doc_side_edit_seen_s'] = round(time.time() - t2, 1)
        b.close()
    path = out_dir / f'{stamp}.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps(result, ensure_ascii=False, indent=1))
    print('記録:', path)


if __name__ == '__main__':
    main()
