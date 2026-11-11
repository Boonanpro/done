"""Real pieces of a page for the parts Dan shows (2026-11-12, the owner: show the real thing, not words with icons).

page_clip opens a page at the phone's width (a browser of this server, not the owner's) and keeps, as Dan's own files
(/api/v1/files/...), what the parts Quote, Item and Image show:
- crop: the block of the page holding the words `find`, cut out, with a highlighter stroke on the words `mark` inside that
  same block only. The 11/12 sample marked a name in an unrelated part of the page: the mark was looked up in the whole
  document, so the first match anywhere got the stroke.
- photo: the page's own picture of the person, shop or product (og:image, else the largest picture near the top).
  Kept here because most sites refuse to give their pictures to another site's page (CORS), and the chat and the call
  screen ask for them that way.

The tool reads public pages only; it does not log in. Nothing is sent anywhere.
"""
import asyncio
import uuid


TOOL = {
    'name': 'page_clip',
    'description': ('ページの本物の一部を、チャットと通話の画面の部品で見せるために取ってくる（ダンのファイルとして保存し /api/v1/files/… を返す）。'
                    'find に書いた言葉がある所をスマホの幅で切り抜き、mark の言葉に蛍光ペンを引いた画像（Quote の image・Image に使う）。'
                    'photo=true でそのページの人・店・物の写真（Item の image に使う）。ログインの要らないページだけ。'),
    'input_schema': {'type': 'object', 'properties': {
        'url': {'type': 'string', 'description': 'ページの https:// の URL'},
        'find': {'type': 'string', 'description': '切り抜く所にある言葉（ページに書いてあるとおり。例: 院長 仲江政史）'},
        'mark': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 4, 'description': '切り抜いた所の中で蛍光ペンを引く言葉'},
        'photo': {'type': 'boolean', 'description': 'そのページの写真（人・店・物）も取る'},
    }, 'required': ['url'], 'additionalProperties': False},
}

UA = ('Mozilla/5.0 (Linux; Android 14; SM-S931Q) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36')
WIDTH = 390
PAGE_S = 25
PHOTO_MAX = 8 * 1024 * 1024

# The block that holds `find` (the smallest element whose text has it), the strokes on `mark` inside that block only,
# and the rectangle to cut (a long paragraph is cut around the first stroke).
CLIP_JS = r"""
([find, marks]) => {
  const norm = (s) => (s || '').replace(/\s+/g, '');
  const want = norm(find);
  let el = null;
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  while (walk.nextNode()) {
    const n = walk.currentNode;
    if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(n.tagName)) continue;
    if (!norm(n.innerText).includes(want)) continue;
    const r = n.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    el = n;   // deeper matches come later in document order: the last one holding the words is the smallest block
  }
  if (!el) return null;
  // grow a one-line hit to its paragraph-sized block so the crop has context
  while (el.parentElement && el.getBoundingClientRect().height < 60 && el.parentElement !== document.body
         && el.parentElement.getBoundingClientRect().height < 260) el = el.parentElement;
  // only the block is photographed: everything beside it (menus, the next column, headers pinned to the screen) is
  // hidden, so a crop of a page built for a PC does not carry pieces of other parts
  for (const n of document.querySelectorAll('body *')) {
    if (!n.contains(el) && !el.contains(n)) n.style.visibility = 'hidden';
  }
  el.scrollIntoView({block: 'center'});
  let first = null;
  const strokes = [];
  for (const m of marks || []) {
    if (!m) continue;
    // the page may write 仲江 政史 with a space (or a line break) where Dan writes 仲江政史
    const re = new RegExp([...m.replace(/\s+/g, '')].map((c) => c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('[\\s\u3000]*'));
    const tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (tw.nextNode()) {
      const t = tw.currentNode, hit = re.exec(t.nodeValue);
      if (!hit) continue;
      const range = document.createRange(); range.setStart(t, hit.index); range.setEnd(t, hit.index + hit[0].length);
      for (const b of range.getClientRects()) {
        const d = document.createElement('div');
        Object.assign(d.style, {position: 'absolute', left: (b.left + scrollX - 2) + 'px', top: (b.top + scrollY + b.height * 0.45) + 'px',
          width: (b.width + 4) + 'px', height: (b.height * 0.55) + 'px', background: 'rgba(255, 214, 10, .6)', zIndex: 2147483647,
          pointerEvents: 'none', borderRadius: '2px', mixBlendMode: 'multiply'});
        document.body.appendChild(d);
        strokes.push(m);
        if (!first) first = {y: b.top + scrollY, h: b.height, right: b.right + scrollX};
      }
      break;
    }
  }
  const b = el.getBoundingClientRect();
  const box = {x: b.left + scrollX, y: b.top + scrollY, w: b.width, h: b.height};
  // across, only as wide as the words in it (a table row of a page built for a PC is mostly empty)
  const cr = document.createRange(); cr.selectNodeContents(el);
  const t = cr.getBoundingClientRect();
  if (t.width > 20 && t.width < b.width - 40) { box.x = Math.max(b.left, t.left - 14) + scrollX; box.w = Math.min(b.right, t.right + 14) + scrollX - box.x; }
  // one line (a row of a table: 院長 ... 仲江 政史 ... ): end just after the marked words, so the words come out large
  if (first && box.h < 70 && first.right + 24 < box.x + box.w) box.w = first.right + 24 - box.x;
  if (first && box.h > 320) {
    // a long block: five lines around the stroke, cut on the lines (not through them)
    const cs = getComputedStyle(el);
    const fs = parseFloat(cs.fontSize) || 16;
    const lh = parseFloat(cs.lineHeight) || fs * 1.6;
    const top0 = box.y + (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.borderTopWidth) || 0);
    const k = Math.max(0, Math.floor((first.y + first.h / 2 - top0) / lh));
    const y = top0 + Math.max(0, k - 2) * lh;
    box.h = Math.min(5 * lh, box.y + box.h - y); box.y = y;
  }
  return {box, marked: strokes, page_width: document.documentElement.scrollWidth};
}
"""

PHOTO_JS = r"""
() => {
  // the page's own photo of the person, shop or product: the largest picture near the top that is not a logo or an
  // icon (small sites give their logo as og:image: Personal Care's was a 512x512 mark), else og:image if it is not one
  const logo = /logo|icon|favicon|sprite|cropped-|banner|btn|button|line_|instagram|twitter|facebook|youtube/i;
  const abs = (u) => { try { return new URL(u, location.href).href; } catch { return null; } };
  let best = null, area = 0;
  for (const img of document.images) {
    const r = img.getBoundingClientRect();
    const src = img.currentSrc || img.src;
    if (!src || logo.test(src) || logo.test(img.alt || '') || r.top + scrollY > 3000 || r.width < 160 || r.height < 110) continue;
    const ratio = r.width / r.height;
    if (ratio > 4 || ratio < 0.4) continue;
    const a = r.width * r.height;
    if (a > area) { best = src; area = a; }
  }
  if (best) return abs(best);
  const og = document.querySelector('meta[property="og:image"], meta[name="og:image"], meta[name="twitter:image"]');
  return og && og.content && !logo.test(og.content) ? abs(og.content) : null;
}
"""


def _save(data: bytes, ext: str) -> str:
    from app.api.file_routes import UPLOAD_DIR
    name = f'clip-{uuid.uuid4().hex}.{ext}'
    (UPLOAD_DIR / name).write_bytes(data)
    return '/api/v1/files/' + name


def _ext(content_type: str, url: str) -> str | None:
    ct = (content_type or '').split(';')[0].strip().lower()
    for key, ext in (('image/png', 'png'), ('image/jpeg', 'jpg'), ('image/jpg', 'jpg'), ('image/webp', 'webp'), ('image/gif', 'gif')):
        if ct == key: return ext
    return None


async def clip(url: str, find: str = '', mark=None, photo: bool = False) -> dict:
    url = str(url or '').strip()
    if not url.startswith('https://') and not url.startswith('http://'):
        return {'success': False, 'error': 'https:// の URL を渡す'}
    marks = [str(m).strip() for m in (mark or []) if str(m).strip()][:4]
    from playwright.async_api import async_playwright
    out: dict = {'success': True, 'url': url}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            ctx = await browser.new_context(viewport={'width': WIDTH, 'height': 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                                            locale='ja-JP', user_agent=UA, ignore_https_errors=True)
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=PAGE_S * 1000)
                try: await page.wait_for_load_state('networkidle', timeout=6000)
                except Exception: pass
            except Exception as exc:
                return {'success': False, 'error': f'ページを開けなかった: {type(exc).__name__}'}
            out['title'] = (await page.title() or '')[:120]
            if find.strip():
                found = await page.evaluate(CLIP_JS, [find.strip(), marks])
                if not found:
                    out['crop'] = None
                    out['crop_note'] = f'「{find.strip()[:40]}」はページに見つからなかった'
                else:
                    await page.wait_for_timeout(200)
                    b, pw = found['box'], found['page_width']
                    x0 = max(0, b['x'] - 6)
                    w = min(pw - x0, b['w'] + 12)
                    top = max(0, b['y'] - 12)
                    png = await page.screenshot(clip={'x': x0, 'y': top, 'width': w, 'height': min(b['h'] + 24, 900)}, full_page=True)
                    out['crop'] = _save(png, 'png')
                    out['marked'] = found['marked']
                    missing = [m for m in marks if m not in found['marked']]
                    if missing: out['mark_note'] = '切り抜いた所に無かった言葉（線は引いていない）: ' + '、'.join(missing)
            if photo:
                src = await page.evaluate(PHOTO_JS)
                out['photo'] = None
                if src:
                    try:
                        r = await ctx.request.get(src, timeout=15000, headers={'Referer': url})
                        body = await r.body()
                        ext = _ext(r.headers.get('content-type', ''), src)
                        if r.ok and ext and len(body) <= PHOTO_MAX:
                            out['photo'] = _save(body, ext)
                    except Exception:
                        pass
                if not out['photo']: out['photo_note'] = 'このページから写真を取れなかった'
        finally:
            await browser.close()
    return out


async def tool(params: dict) -> dict:
    try:
        return await asyncio.wait_for(clip(params.get('url', ''), str(params.get('find') or ''), params.get('mark') or [], bool(params.get('photo'))), 60)
    except asyncio.TimeoutError:
        return {'success': False, 'error': '60秒で取れなかった'}
