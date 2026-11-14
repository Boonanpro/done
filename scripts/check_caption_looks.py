"""Draw caption looks the way the editor does and check them (2026-11-14).

For each look: the EXPORT path (scripts/render_caption_pngs.py, the step the export burns in) and
the PREVIEW path (the /native-caption-overlay page: @font-face + the same <CaptionLayer>) are
screenshotted at the output size, laid over a background frame, and compared. It also reads which
font faces the page actually loaded, so an owner font that silently fell back is a failure.

Usage:
  python scripts/check_caption_looks.py --base http://127.0.0.1:3002 --bg frame.png --out DIR \
      [--text 勉強より先に事業を始めてください] [--looks looks.json]
Exit 1 when a look's font did not load or preview and export differ.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The three looks the owner asked for. These are also the style objects to pass to set_clip.
LOOKS = {
    'plain': {'font': 'hiragino-w6', 'color': '#ffffff', 'outlineColor': '#000000', 'outlineWidth': 1.4,
              'shadow': {'color': 'rgba(0,0,0,0.5)', 'blur': 6, 'dx': 0, 'dy': 3}},
    'red_box': {'font': 'toppan-mincho', 'color': '#ffffff', 'outlineWidth': 0, 'fontSize': 1.15,
                'bg': {'color': '#c8101a', 'opacity': 1, 'radius': 0, 'padX': 0.45, 'padY': 0.16}},
    'red_slant': {'font': 'noto-sans', 'color': '#e3141f', 'outlineColor': '#ffffff', 'outlineWidth': 2.6,
                  'skew': -9, 'fontSize': 1.6, 'maxWidth': 0.94, 'shadow': {'color': 'rgba(0,0,0,0.45)', 'blur': 10, 'dx': 0, 'dy': 5}},
}
# cssFamily the page must have loaded for each font id (fallback = failure)
FAMILY = {'hiragino-w6': 'HiraginoW6', 'hiragino-w8': 'HiraginoW8', 'toppan-mincho': 'ToppanMidashiMincho',
          'noto-sans': 'NotoSansJP', 'mincho': 'ShipporiMincho'}


def export_png(base: str, w: int, h: int, text: str, design: dict, png: Path) -> None:
    spec = {'outW': w, 'outH': h, 'web_base': base,
            'items': [{'png': str(png), 'text': text, 'time': 0.0, 'design': design, 'words': []}]}
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False)
    r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'render_caption_pngs.py'), f.name],
                       capture_output=True, text=True, timeout=180)
    Path(f.name).unlink(missing_ok=True)
    if not png.exists():
        raise RuntimeError(f'export render failed: {r.stdout} {r.stderr[-800:]}')


def preview_png(page, base: str, w: int, h: int, text: str, design: dict, png: Path) -> list[str]:
    page.goto(f'{base}/native-caption-overlay', wait_until='domcontentloaded', timeout=60000)
    page.wait_for_function("() => typeof window.__setNativeCaptionPayload === 'function'", timeout=60000)
    page.evaluate('(p) => window.__setNativeCaptionPayload(p)',
                  {'outW': w, 'outH': h, 'time': 0.5,
                   'captions': [{'text': text, 'start': 0, 'end': 10, 'design': design}]})
    fam = FAMILY.get(design.get('font', 'noto-sans'))
    try:
        page.wait_for_function(
            "(fam) => [...document.fonts].some(f => f.family.replace(/\"/g,'') === fam && f.status === 'loaded')",
            arg=fam, timeout=20000)
    except Exception:  # noqa: BLE001 - the font never loaded: reported as BAD below
        pass
    page.evaluate('() => document.fonts.ready')
    page.wait_for_timeout(300)
    page.screenshot(path=str(png), omit_background=True, clip={'x': 0, 'y': 0, 'width': w, 'height': h})
    return page.evaluate("() => [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family.replace(/\"/g,''))")


def export_fonts(page, base: str, w: int, h: int, text: str, design: dict) -> list[str]:
    """Which faces the export page (/caption-frame) loaded for this caption."""
    import base64
    payload = {'outW': w, 'outH': h, 'time': 0.0,
               'captions': [{'text': text, 'start': 0, 'end': 1e9, 'design': design, 'words': []}]}
    raw = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
    page.goto(f'{base}/caption-frame?p={raw}', wait_until='domcontentloaded', timeout=60000)
    page.wait_for_selector("body[data-caption-ready='1']", state='attached', timeout=30000)
    return page.evaluate("() => [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family.replace(/\"/g,''))")


def ink_of(img) -> int:
    return sum(img.getchannel('A').point(lambda v: 255 if v > 10 else 0).histogram()[255:])


def blocked_font_ink(page, base: str, w: int, h: int, text: str, design: dict, png: Path) -> int:
    """The export page with the owner font files unreachable: the caption must still draw
    (in its fallback font) and the page must still become ready."""
    import base64
    page.route('**/scene-vendor/fonts/**', lambda route: route.abort())
    try:
        payload = {'outW': w, 'outH': h, 'time': 0.0,
                   'captions': [{'text': text, 'start': 0, 'end': 1e9, 'design': design, 'words': []}]}
        raw = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
        page.goto(f'{base}/caption-frame?p={raw}', wait_until='domcontentloaded', timeout=60000)
        page.wait_for_selector("body[data-caption-ready='1']", state='attached', timeout=15000)
        page.wait_for_timeout(200)
        page.screenshot(path=str(png), omit_background=True, clip={'x': 0, 'y': 0, 'width': w, 'height': h})
    finally:
        page.unroute('**/scene-vendor/fonts/**')
    from PIL import Image
    return ink_of(Image.open(png).convert('RGBA'))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:3000')
    ap.add_argument('--bg', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--text', default='勉強より先に事業を始めてください')
    ap.add_argument('--looks', help='JSON file {name: style} replacing the built-in looks')
    a = ap.parse_args()
    from PIL import Image, ImageChops
    from playwright.sync_api import sync_playwright

    looks = json.loads(Path(a.looks).read_text(encoding='utf-8')) if a.looks else LOOKS
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    bg = Image.open(a.bg).convert('RGBA')
    w, h = bg.size
    bad = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, channel='chrome')
        page = browser.new_page(viewport={'width': w, 'height': h}, device_scale_factor=1)
        for name, design in looks.items():
            fam = FAMILY.get(design.get('font', 'noto-sans'))
            exp, pre = out / f'{name}_export.png', out / f'{name}_preview.png'
            export_png(a.base, w, h, a.text, design, exp)
            loaded_export = export_fonts(page, a.base, w, h, a.text, design)
            loaded_preview = preview_png(page, a.base, w, h, a.text, design, pre)
            ea, pa = Image.open(exp).convert('RGBA'), Image.open(pre).convert('RGBA')
            diff = ImageChops.difference(ea, pa).convert('L')
            changed = sum(diff.point(lambda v: 255 if v > 40 else 0).histogram()[255:])
            ink = ink_of(ea)
            frame = bg.copy()
            frame.alpha_composite(ea)
            frame.convert('RGB').save(out / f'{name}.png')
            ok = fam in loaded_export and fam in loaded_preview and ink > 500 and changed <= max(50, ink * 0.002)
            extra = ''
            if design.get('skew'):
                # the slant must actually change the drawing (old renderers ignored the key)
                flat = out / f'{name}_noskew.png'
                export_png(a.base, w, h, a.text, {**design, 'skew': 0}, flat)
                slant_px = sum(ImageChops.difference(ea, Image.open(flat).convert('RGBA')).convert('L')
                               .point(lambda v: 255 if v > 40 else 0).histogram()[255:])
                ok = ok and slant_px > ink * 0.05
                extra += f' slant_changed_px={slant_px}'
            if fam not in ('NotoSansJP', 'ShipporiMincho'):
                fb = blocked_font_ink(page, a.base, w, h, a.text, design, out / f'{name}_font_blocked.png')
                ok = ok and fb > 500
                extra += f' ink_when_font_unreachable={fb}'
            bad += not ok
            print(f"{'OK ' if ok else 'BAD'} {name}: font={design.get('font')} export_loaded={fam in loaded_export} "
                  f"preview_loaded={fam in loaded_preview} ink_px={ink} preview_vs_export_px={changed}{extra} "
                  f"-> {out / (name + '.png')}")
        browser.close()
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
