"""Reading and locating without model-written JavaScript.

A month of transcripts: 1,175 evaluate calls, most of them to read page text
after an action, to find an element by its visible text, or to click it. Each
cost a model round trip spent writing JS. These are the fixed forms of those
three needs. Read-only except for tagging a found element with a ref so the
ordinary guarded click can act on it.
"""
import json

# Shared by every snippet: open shadow roots, visibility, text, and the same
# ref bookkeeping the element listing uses (so refs stay valid across both).
PRELUDE = r"""
const deep = s => window.__danDeep ? window.__danDeep(s) : [...document.querySelectorAll(s)];
const norm = s => (s || '').replace(/\s+/g, ' ').trim();
const vis = e => {const r=e.getBoundingClientRect(),s=getComputedStyle(e);
  return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'};
const label = e => norm(e.innerText || e.value || e.getAttribute('aria-label') || e.getAttribute('alt') || e.getAttribute('title') || e.placeholder || '');
const CLICKABLE = 'a,button,input,select,textarea,label,summary,[role="button"],[role="link"],[role="tab"],[role="menuitem"],[role="option"],[role="checkbox"],[role="radio"],[onclick],[tabindex]:not([tabindex="-1"])';
const refOf = e => {
  const state = window.__danRefState;
  if (!state || state.version !== 2) return null;
  let ref = state.nodes.get(e);
  if (!ref) { ref = `${state.prefix}:${(state.next++).toString(36)}`; state.nodes.set(e, ref); }
  e.setAttribute('data-dan-ref', ref);
  return '@' + ref;
};
const describe = e => ({ref: refOf(e), tag: e.tagName.toLowerCase(), role: e.getAttribute('role') || '', text: label(e).slice(0, 120),
  href: e.getAttribute('href') || '', onclick: (e.getAttribute('onclick') || '').slice(0, 100), disabled: !!e.disabled});
"""

PAGE_TEXT = "(limit) => {" + PRELUDE + r"""
  const main = deep('main,[role="main"],article').filter(vis).sort((a,b)=>b.innerText.length-a.innerText.length)[0];
  const root = main && main.innerText.trim().length > 200 ? main : document.body;
  const text = (root ? root.innerText : '').replace(/\n{3,}/g, '\n\n').trim();
  return {text: text.slice(0, limit), total: text.length, scope: root === document.body ? 'page' : 'main'};
}"""

FIND = "(args) => {" + PRELUDE + r"""
  let test;
  if (args.regex) { const re = new RegExp(args.query, 'i'); test = t => re.test(t); }
  else { const q = args.query.toLowerCase(); test = t => t.toLowerCase().includes(q); }
  const pool = deep('a,button,input,select,textarea,label,summary,[role],[onclick],td,th,li,dt,dd,p,span,div,h1,h2,h3,h4,h5,h6')
    .filter(e => vis(e) && test(label(e))).slice(0, 600);
  const set = new Set(pool);
  // The smallest element carrying the text, not every ancestor that contains it.
  const hits = pool.filter(e => ![...e.children].some(c => set.has(c)) && ![...e.querySelectorAll('*')].some(c => set.has(c)));
  const seen = new Set(), out = [];
  for (const e of hits) {
    const target = e.closest(CLICKABLE) || e;
    if (seen.has(target)) continue;
    seen.add(target);
    const item = describe(target);
    item.clickable = target.matches(CLICKABLE);
    item.matched = label(e).slice(0, 160);
    const around = e.parentElement ? norm(e.parentElement.innerText) : '';
    if (around && around !== item.matched) item.context = around.slice(0, 200);
    out.push(item);
    if (out.length >= args.limit) break;
  }
  return {url: location.href, count: hits.length, results: out};
}"""

# Exact label first, then containment. Only elements a person could click.
LOCATE = "(args) => {" + PRELUDE + r"""
  const want = norm(args.label), lower = want.toLowerCase();
  let pool = deep(CLICKABLE).filter(e => vis(e) && !e.disabled);
  if (args.role) pool = pool.filter(e => (e.getAttribute('role') || ({A:'link',BUTTON:'button'}[e.tagName]) || e.tagName.toLowerCase()) === args.role);
  const outer = list => list.filter(e => !list.some(o => o !== e && o.contains(e)));  // <a><span>次へ</span></a> is one target
  let found = outer(pool.filter(e => label(e) === want));
  let exact = true;
  if (!found.length) { exact = false; found = outer(pool.filter(e => label(e).toLowerCase().includes(lower))); }
  return {url: location.href, exact, candidates: found.slice(0, 12).map(describe), count: found.length};
}"""

READ = "(args) => {" + PRELUDE + r"""
  let root = document.body, scope = 'page';
  if (args.selector) {
    const nodes = deep(args.selector);
    if (!nodes.length) return {error: 'selector_not_found'};
    // the first match with words: a guessed list like "#main, .main-contents, article" often hits an empty wrapper first
    // (2026-09-23 EX: 121 characters, then a JavaScript read of the whole page)
    const worded = nodes.find(n => (n.innerText || '').trim());
    if (worded) { root = worded; scope = 'selector (' + nodes.length + ' match)'; }
    else scope = 'page (selector matched only empty elements)';
  } else {
    const main = deep('main,[role="main"],article').filter(vis).sort((a,b)=>b.innerText.length-a.innerText.length)[0];
    if (main && main.innerText.trim().length > 200) { root = main; scope = 'main'; }
  }
  const out = {url: location.href, title: document.title, scope};
  if (args.tables) {
    out.tables = [...root.querySelectorAll('table')].filter(vis).slice(0, 8).map(t => ({
      rows: [...t.rows].slice(0, args.max_rows).map(r => [...r.cells].map(c => norm(c.innerText)).join(' | ')),
      total_rows: t.rows.length}));
  }
  let text = (root.innerText || '').replace(/\n{3,}/g, '\n\n').trim();
  out.total_chars = text.length;
  let start = args.offset || 0;
  if (args.after) {
    const i = text.indexOf(args.after);
    if (i < 0) { out.after_found = false; } else { out.after_found = true; start = i; }
  }
  out.offset = start;
  out.text = text.slice(start, start + args.max_chars);
  out.truncated = start + args.max_chars < text.length;
  return out;
}"""


async def page_text(page, limit):
    result = await page.evaluate(PAGE_TEXT, limit)
    return result if isinstance(result, dict) else {'text': '', 'total': 0, 'scope': 'page'}


async def _ensure_refs(page):
    if not await page.evaluate("() => !!(window.__danRefState && window.__danRefState.version === 2 && window.__danDeep)"):
        await page.get_interactive_elements()


async def find(page, params):
    query = params.get('query')
    if not isinstance(query, str) or not query.strip() or len(query) > 300:
        return {'success': False, 'error': 'query（探したい表示文字。1〜300字）が必要です'}
    limit = params.get('limit', 20)
    if type(limit) != int or not 1 <= limit <= 50:
        return {'success': False, 'error': 'limit は 1〜50'}
    await _ensure_refs(page)
    try:
        result = await page.evaluate(FIND, {'query': query.strip(), 'regex': bool(params.get('regex')), 'limit': limit})
    except Exception as exc:
        return {'success': False, 'error': 'find に失敗しました（regex の書式を確認）: '+type(exc).__name__}
    lines = [f"find {json.dumps(query, ensure_ascii=False)}: {result['count']} 件（表示 {len(result['results'])} 件） URL: {result['url']}"]
    for item in result['results']:
        extra = ''.join(f' {k}={json.dumps(item[k], ensure_ascii=False)}' for k in ('href', 'onclick', 'context') if item.get(k))
        lines.append(f"  {item['ref']}: [{item['tag']}{', role='+item['role'] if item['role'] else ''}]"
                     f"{'' if item['clickable'] else ' (クリック対象ではない文字)'}{' (disabled)' if item['disabled'] else ''} {item['text']}{extra}")
    if not result['results']:
        lines.append('  見つかりません。画面外・別タブ・iframe 内の可能性。scroll か read で確認。')
    else:
        lines.append('ref はそのまま click / type / select に使えます。')
    return {'success': True, 'count': result['count'], 'results': result['results'],
            'content': [{'type': 'text', 'text': '\n'.join(lines)}]}


async def locate(page, params):
    """Resolve click(label=...) to one ref, or explain why not. Never clicks."""
    await _ensure_refs(page)
    result = await page.evaluate(LOCATE, {'label': params['label'], 'role': params.get('role')})
    if result['count'] == 1:
        return result['candidates'][0]['ref'], None
    if result['count'] == 0:
        text = f"label {json.dumps(params['label'], ensure_ascii=False)} に一致するクリック対象が見えていません。find で探すか、scroll / screenshot で確認してください。何もクリックしていません。"
    else:
        text = (f"label {json.dumps(params['label'], ensure_ascii=False)} に一致するクリック対象が {result['count']} 個あります。何もクリックしていません。"
                "下の ref で click してください:\n" + '\n'.join(
                    f"  {c['ref']}: [{c['tag']}] {c['text']}" + (f" href={c['href']}" if c['href'] else '') for c in result['candidates']))
    return None, {'success': False, 'dispatched': False, 'reason': 'label_not_unique' if result['count'] else 'label_not_found',
                  'candidates': result['candidates'], 'content': [{'type': 'text', 'text': text}]}


async def read(page, params):
    max_chars = params.get('max_chars', 4000)
    offset = params.get('offset', 0)
    if type(max_chars) != int or not 100 <= max_chars <= 12000 or type(offset) != int or offset < 0:
        return {'success': False, 'error': 'max_chars は 100〜12000、offset は 0 以上'}
    args = {'selector': params.get('selector'), 'after': params.get('after'), 'offset': offset, 'max_chars': max_chars,
            'tables': bool(params.get('tables')), 'max_rows': 200}
    try:
        result = await page.evaluate(READ, args)
    except Exception as exc:
        return {'success': False, 'error': 'read に失敗しました（selector の書式を確認）: '+type(exc).__name__}
    if result.get('error'):
        return {'success': False, 'error': 'selector に一致する要素がありません'}
    head = f"URL: {result['url']}\nタイトル: {result['title']}\n範囲: {result['scope']} / 全{result['total_chars']}字中 {result['offset']}字目から"
    if params.get('after') and not result.get('after_found'):
        head += f"\nafter {json.dumps(params['after'], ensure_ascii=False)} は本文に見つからなかったため offset から読んでいます。"
    parts = [head]
    for i, table in enumerate(result.get('tables') or []):
        parts.append(f"表{i+1}（全{table['total_rows']}行）:\n" + '\n'.join(table['rows']))
    parts.append('本文:\n'+result['text'])
    if result['truncated']:
        parts.append(f"（続きは offset={result['offset']+max_chars} で読めます）")
    return {'success': True, 'content': [{'type': 'text', 'text': '\n\n'.join(parts)}]}
