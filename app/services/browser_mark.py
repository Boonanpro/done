"""A screenshot of Dan's browser with red rings and arrows on the things to look at (2026-11-16).

The owner asked where the Pin story was on the board (11/13) and got a paragraph. A picture of the real screen with a
ring on the button to press says it at a glance. browser(action="mark", marks=[{ref|query, label}]) finds the elements
on the page Dan has open (logged in, after navigating), takes a screenshot, draws the rings, arrows and labels on the
saved image (the page itself is not touched: the session is shared), and keeps it as Dan's file (/api/v1/files/...).
"""
import base64
import io
import uuid
from pathlib import Path

MARKS_MAX = 6
RED = (230, 30, 40)
FONT_FILES = ('/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc', '/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc',
              'C:/Windows/Fonts/meiryob.ttc', 'C:/Windows/Fonts/meiryo.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc')

# Each mark is a ref from the element list (or find) or the visible words of the thing. The words find the smallest
# visible element that carries them, the way find does. The first target is scrolled into view when it is off screen.
LOCATE_JS = r"""
(marks) => {
  const deep = s => window.__danDeep ? window.__danDeep(s) : [...document.querySelectorAll(s)];
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const text = e => norm(e.innerText || e.value || e.getAttribute('aria-label') || e.getAttribute('alt') || e.getAttribute('title') || '');
  const pick = (m) => {
    if (m.ref) return deep(`[data-dan-ref="${String(m.ref).replace(/^@/, '').replace(/"/g, '')}"]`).find(vis) || null;
    const q = norm(m.query);
    if (!q) return null;
    const pool = deep('a,button,input,select,textarea,label,summary,img,svg,[role],[onclick],td,th,li,dt,dd,p,span,div,h1,h2,h3,h4,h5,h6,section,article')
      .filter(e => vis(e) && text(e).includes(q)).slice(0, 800);
    const set = new Set(pool);
    const hits = pool.filter(e => ![...e.querySelectorAll('*')].some(c => set.has(c)));
    // on screen first, then the smallest
    hits.sort((a, b) => { const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      const on = r => r.bottom > 0 && r.top < innerHeight ? 0 : 1;
      return on(ra) - on(rb) || ra.width * ra.height - rb.width * rb.height; });
    return hits[0] || null;
  };
  const els = marks.map(pick);
  const first = els.find(Boolean);
  if (first) { const r = first.getBoundingClientRect(); if (r.top < 0 || r.bottom > innerHeight) first.scrollIntoView({block: 'center'}); }
  return {vw: innerWidth, vh: innerHeight, boxes: els.map(e => { if (!e) return null; const r = e.getBoundingClientRect();
    return {x: r.left, y: r.top, w: r.width, h: r.height, on: r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth}; })};
}
"""


def _font(size):
    from PIL import ImageFont
    for f in FONT_FILES:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _toward(box, px, py):
    """The point on the box's edge facing (px, py)."""
    x0, y0, x1, y1 = box
    return min(max(px, x0), x1), min(max(py, y0), y1)


def _arrow(draw, start, end, width, color):
    import math
    draw.line([start, end], fill=color, width=width)
    ang = math.atan2(end[1] - start[1], end[0] - start[0])
    head = width * 4.5
    for side in (2.6, -2.6):
        draw.line([end, (end[0] - head * math.cos(ang + side / 6), end[1] - head * math.sin(ang + side / 6))], fill=color, width=width)
    pts = [end, (end[0] - head * math.cos(ang + 0.45), end[1] - head * math.sin(ang + 0.45)),
           (end[0] - head * math.cos(ang - 0.45), end[1] - head * math.sin(ang - 0.45))]
    draw.polygon(pts, fill=color)


def draw_marks(png: bytes, vw: float, boxes: list, labels: list) -> bytes:
    """Rings, arrows and labels drawn on the screenshot. Element boxes are in CSS pixels; the picture's scale is its
    width over the page's inner width (no assumption about the device pixel ratio)."""
    from PIL import Image, ImageDraw, ImageStat
    im = Image.open(io.BytesIO(png)).convert('RGB')
    gray = im.convert('L')
    W, H = im.size
    k = W / vw if vw else 1.0
    draw = ImageDraw.Draw(im)
    stroke = max(3, round(3.5 * k))
    font = _font(max(14, round(17 * k)))
    rings = []
    for b in boxes:
        if not b:
            rings.append(None)
            continue
        pad = 7 * k
        x0, y0 = max(stroke, b['x'] * k - pad), max(stroke, b['y'] * k - pad)
        x1, y1 = min(W - stroke, (b['x'] + b['w']) * k + pad), min(H - stroke, (b['y'] + b['h']) * k + pad)
        rings.append((x0, y0, x1, y1))
    taken = [r for r in rings if r]
    for i, ring in enumerate(rings):
        if not ring:
            continue
        x0, y0, x1, y1 = ring
        draw.rounded_rectangle(ring, radius=min(18 * k, (y1 - y0) / 2, (x1 - x0) / 2), outline=RED, width=stroke)
        text = (labels[i] or '').strip() or str(i + 1)
        tb = draw.textbbox((0, 0), text, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        lw, lh = tw + 18 * k, th + 14 * k
        gap = 56 * k
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        # a label beside the ring with an arrow to it
        spots = [(cx - lw / 2 + gap * 0.6, y1 + gap), (cx - lw / 2 + gap * 0.6, y0 - gap - lh), (x1 + gap, cy - lh / 2 + gap * 0.5),
                 (x0 - gap - lw, cy - lh / 2 + gap * 0.5), (cx - lw / 2 - gap * 0.6, y1 + gap), (cx - lw / 2 - gap * 0.6, y0 - gap - lh)]
        # among the spots that fit and cover no ring, the emptiest one (least detail under it): the label hides no words
        lab, calm = None, None
        for lx, ly in spots:
            lx, ly = min(max(4, lx), W - lw - 4), min(max(4, ly), H - lh - 4)
            cand = (lx, ly, lx + lw, ly + lh)
            if any(_overlap(cand, r) for r in taken):
                continue
            busy = ImageStat.Stat(gray.crop(tuple(round(v) for v in cand))).stddev[0]
            if calm is None or busy < calm - 2:
                lab, calm = cand, busy
        if lab is None:   # no free room: the label sits on the ring's top edge, no arrow
            lx, ly = min(max(4, x0), W - lw - 4), max(4, y0 - lh / 2)
            lab = (lx, ly, lx + lw, ly + lh)
        else:
            lcx, lcy = (lab[0] + lab[2]) / 2, (lab[1] + lab[3]) / 2
            start = _toward(lab, cx, cy)
            end = _toward((x0 - stroke, y0 - stroke, x1 + stroke, y1 + stroke), lcx, lcy)
            _arrow(draw, start, end, stroke, RED)
        taken.append(lab)
        draw.rounded_rectangle(lab, radius=8 * k, fill=RED)
        draw.text((lab[0] + 9 * k - tb[0], lab[1] + 7 * k - tb[1]), text, fill=(255, 255, 255), font=font)
    out = io.BytesIO()
    im.save(out, 'PNG', optimize=True)
    return out.getvalue()


def _save(png: bytes) -> str:
    from app.api.file_routes import UPLOAD_DIR
    name = f'mark-{uuid.uuid4().hex}.png'
    (UPLOAD_DIR / name).write_bytes(png)
    return '/api/v1/files/' + name


async def mark(page, params: dict) -> dict:
    raw = params.get('marks')
    if not isinstance(raw, list) or not raw:
        return {'success': False, 'error': 'marks に印を付ける物を1〜6個（ref か query、任意で label）'}
    marks = []
    for m in raw[:MARKS_MAX]:
        m = m if isinstance(m, dict) else {'query': str(m)}
        marks.append({'ref': str(m.get('ref') or '').strip(), 'query': str(m.get('query') or '').strip(),
                      'label': str(m.get('label') or '').strip()[:40]})
    found = await page.evaluate(LOCATE_JS, [{'ref': m['ref'], 'query': m['query']} for m in marks])
    await page.wait_for_timeout(250)   # a scroll into view settles
    found = await page.evaluate(LOCATE_JS, [{'ref': m['ref'], 'query': m['query']} for m in marks])
    shot = await page.screenshot_base64(full_page=False)
    png = base64.b64decode(shot['base64'] if isinstance(shot, dict) else shot)
    boxes = [b if b and b.get('on') else None for b in found['boxes']]
    missing = [m['ref'] or m['query'] for m, b in zip(marks, found['boxes']) if not b]
    offscreen = [m['ref'] or m['query'] for m, b in zip(marks, found['boxes']) if b and not b.get('on')]
    marked = draw_marks(png, found['vw'], boxes, [m['label'] for m in marks])
    url = _save(marked)
    out = {'success': True, 'url': url, 'marked': sum(1 for b in boxes if b),
           'note': '見せる時は attach_image か部品の image に url を使う'}
    if missing:
        out['not_found'] = missing
    if offscreen:
        out['off_screen'] = offscreen
    from PIL import Image
    small = Image.open(io.BytesIO(marked))
    small.thumbnail((1024, 1024))
    buf = io.BytesIO()
    small.save(buf, 'PNG', optimize=True)
    text = f'印を付けた画面: {url}（{out["marked"]}か所）'
    if missing:
        text += '。見つからなかった物: ' + '、'.join(missing)
    if offscreen:
        text += '。画面の外にあって印を付けられなかった物: ' + '、'.join(offscreen)
    out['content'] = [{'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': base64.b64encode(buf.getvalue()).decode()}},
                      {'type': 'text', 'text': text + '。見せる時は attach_image か部品の image にこの url を使う。'}]
    return out
