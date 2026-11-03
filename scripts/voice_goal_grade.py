"""Pass or fail for a call run against the owner's goal, from facts only (2026-11-03).

Why: the owner refused a check that replayed a failed call word for word and timed it. A call is judged by whether the
owner's goal was reached, and the judgement is made from what can be read back, not from a model's opinion:
  - pages: every page Dan showed on the call's screen is opened here in a plain browser, as the owner would see it. Its
    title must carry the number the owner asked for (a weight, a size) within the scenario's range, and its visible text
    must not say it is sold out. At least `at_least` pages must have been shown. One wrong page shown fails the run,
    since the owner had to notice it and say so.
  - hangup: after the owner asked to hang up, the call must have closed within `within_s`.
  - reply_gap: after each thing the owner said, Dan must have started to answer within `max_s`.
The run is written by scripts/voice_goal_call.py. This file also grades a saved run again, or a hand-made one, which is
how the check itself is tested: a run that showed the 40 kg set of the 13:35 call must fail (python scripts/
voice_goal_grade.py tests/voice_goals/known_bad_40kg.run.json tests/voice_goals/weights_100kg.json).

Usage: python scripts/voice_goal_grade.py <run.json> <scenario.json>   exit 0 = passed, 1 = failed
"""
import asyncio
import json
import re
import sys
from pathlib import Path

BUY = r'カートに入れる|カートへ入れる|買い物かごに入れる|かごに入れる|購入手続き|今すぐ購入|今すぐ買う|購入する|add to cart|buy now'
SOLD = r'売り切れ|在庫切れ|在庫なし|品切れ|SOLD\s?OUT|入荷待ち|販売終了|完売|入荷お知らせ|再入荷'

# What decides "can be bought" is the page's own purchase control, not words anywhere on the page: a review on a page
# that sells the item said 「Amazonで売り切れのため…」 (2026-11-03, the first version of this check failed it). A page with
# schema.org availability is read from there; otherwise from the visible buttons.
READ = '''([BUY, SOLD]) => {
  const buy = new RegExp(BUY, 'i'), sold = new RegExp(SOLD, 'i');
  const h1 = document.querySelector('h1');
  const visible = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const label = el => (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('alt') || '').trim().replace(/\\s+/g, ' ');
  const controls = Array.from(document.querySelectorAll('button, input[type=submit], input[type=button], input[type=image], a, [role=button]')).filter(visible);
  const buttons = controls.map(el => ({text: label(el).slice(0, 40), disabled: !!(el.disabled || el.getAttribute('aria-disabled') === 'true' || /disabled|soldout|sold-out/i.test(el.className || ''))}))
    .filter(b => b.text && (buy.test(b.text) || sold.test(b.text)) && b.text.length <= 40);
  const offers = [];
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try { const walk = o => { if (!o || typeof o !== 'object') return; if (o.availability) offers.push(String(o.availability)); Object.values(o).forEach(walk); }; walk(JSON.parse(s.textContent)); } catch (e) {}
  }
  return {title: document.title || '', h1: h1 ? h1.innerText.trim() : '', text: (document.body ? document.body.innerText : '').slice(0, 20000), buttons, offers};
}'''


async def read_page(context, url):
    """What the owner sees on a page: its title and heading, and whether it can be bought (its availability or its buttons)."""
    page = await context.new_page()
    try:
        response = await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        try: await page.wait_for_load_state('networkidle', timeout=8000)
        except Exception: pass
        seen = await page.evaluate(READ, [BUY, SOLD])
        status = response.status if response else 0
        final = page.url
    except Exception as exc:
        return {'url': url, 'error': f'{type(exc).__name__}: {str(exc)[:160]}'}
    finally:
        await page.close()
    buyable = [b['text'] for b in seen['buttons'] if re.search(BUY, b['text'], re.I) and not b['disabled'] and not re.search(SOLD, b['text'], re.I)]
    sold = [b['text'] for b in seen['buttons'] if re.search(SOLD, b['text'], re.I) or (b['disabled'] and re.search(BUY, b['text'], re.I))]
    offers = seen['offers']
    if offers:
        stock = 'in_stock' if any(re.search(r'InStock|LimitedAvailability|PreOrder', o) for o in offers) else 'sold_out'
        how = 'availability: ' + ', '.join(sorted(set(o.rsplit('/', 1)[-1] for o in offers)))
    elif buyable:
        stock, how = 'in_stock', '押せる「' + buyable[0] + '」'
    elif sold:
        stock, how = 'sold_out', '「' + sold[0] + '」'
    else:
        stock, how = 'unknown', '買うボタンが見つからない'
    return {'url': url, 'final_url': final, 'status': status, 'title': seen['title'].strip()[:200], 'h1': seen['h1'][:200],
            'stock': stock, 'stock_how': how, 'text_head': ' '.join(seen['text'].split())[:600]}


def title_number(page, rule):
    """The first number the rule's pattern finds in the page's title (or heading when the title has none)."""
    for where in (page.get('title') or '', page.get('h1') or ''):
        found = re.search(rule['pattern'], where.replace('，', ',').replace('．', '.'))
        if found:
            return float(found.group(1).replace(',', ''))
    return None


def judge_page(page, rule):
    if page.get('error') or page.get('status', 200) >= 400:
        return False, f"開けなかった（{page.get('error') or page.get('status')}）"
    reasons = []
    number = title_number(page, rule)
    if number is None:
        reasons.append(f"題に{rule.get('unit', '数')}が無い")
    elif not (rule.get('min', float('-inf')) <= number <= rule.get('max', float('inf'))):
        reasons.append(f"{number:g}{rule.get('unit', '')}（{rule.get('min', '')}〜{rule.get('max', '')}の外）")
    if rule.get('in_stock', True) and page.get('stock') != 'in_stock':
        reasons.append(('売り切れ: ' if page.get('stock') == 'sold_out' else '買えるか分からない: ') + page.get('stock_how', ''))
    return (not reasons), '、'.join(reasons) or f"{number:g}{rule.get('unit', '')}・{page.get('stock_how', '')}"


async def check_pages(run, rule, context):
    urls = []
    for shown in run.get('pages', []):
        if shown.get('url') and shown['url'] not in urls: urls.append(shown['url'])
    pages = [await read_page(context, u) for u in urls]
    rows = []
    for page in pages:
        ok, why = judge_page(page, rule)
        rows.append({'url': page['url'], 'title': page.get('title', ''), 'fits': ok, 'why': why})
    enough = len(rows) >= rule.get('at_least', 1)
    passed = enough and all(r['fits'] for r in rows)
    note = '' if enough else f"出したページが{len(rows)}件（{rule.get('at_least', 1)}件以上のはず）"
    return {'name': 'pages', 'passed': passed, 'note': note, 'pages': rows}


def check_hangup(run, rule):
    asked, closed = run.get('hangup_asked_at'), run.get('closed_at')
    if asked is None:
        return {'name': 'hangup', 'passed': False, 'note': '本人役が切ってと言う所まで進まなかった'}
    if closed is None or closed < asked:
        return {'name': 'hangup', 'passed': False, 'note': f"切ってと言った後、{run.get('ended_at', 0) - asked:.0f}秒たっても切れなかった"}
    took = closed - asked
    return {'name': 'hangup', 'passed': took <= rule.get('within_s', 10), 'note': f'切ってと言い終えてから{took:.1f}秒で切れた'}


def reply_gaps(run):
    """For each thing the owner said: seconds from the end of the owner's audio to Dan's next words (None: no answer)."""
    turns = run.get('turns', [])
    gaps = []
    for i, turn in enumerate(turns):
        if turn['role'] != 'owner':
            continue
        nxt = next((t for t in turns[i + 1:] if t['role'] == 'dan'), None)
        stop = next((t['start'] for t in turns[i + 1:] if t['role'] == 'owner'), run.get('ended_at'))
        gaps.append(round(nxt['start'] - turn['end'], 1) if nxt and nxt['start'] <= (stop or nxt['start']) else None)
    return gaps


def check_reply_gap(run, rule):
    gaps = reply_gaps(run)
    late = [g for g in gaps if g is None or g > rule.get('max_s', 8)]
    worst = max((g for g in gaps if g is not None), default=None)
    return {'name': 'reply_gap', 'passed': not late, 'gaps': gaps,
            'note': f"一番長い待ち {worst}秒" + (f"、遅い・答えなし {len(late)}回" if late else '')}


async def grade(run, scenario, context=None):
    from playwright.async_api import async_playwright
    checks = []
    async with async_playwright() as p:
        browser = None
        if context is None:
            browser = await p.chromium.launch()
            context = await browser.new_context(locale='ja-JP', viewport={'width': 1280, 'height': 900})
        for rule in scenario.get('checks', []):
            kind = rule['kind']
            if kind == 'pages': checks.append(await check_pages(run, rule, context))
            elif kind == 'hangup': checks.append(check_hangup(run, rule))
            elif kind == 'reply_gap': checks.append(check_reply_gap(run, rule))
            else: checks.append({'name': kind, 'passed': False, 'note': '知らない確かめ方'})
        if browser: await browser.close()
    return {'scenario': scenario.get('name'), 'passed': all(c['passed'] for c in checks), 'checks': checks}


def main(run_path, scenario_path):
    run = json.loads(Path(run_path).read_text(encoding='utf-8'))
    scenario = json.loads(Path(scenario_path).read_text(encoding='utf-8'))
    result = asyncio.run(grade(run, scenario))
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:3]))
