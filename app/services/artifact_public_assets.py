"""Public asset helpers for DAN artifacts.

成果物 (artifact) ごとの favicon / PWA アイコンを生成する。

優先順位（「賢いデフォルト」）:
  1. 明示ロゴ: ``public/artifacts/<slug>/logo.{png,jpg,jpeg,webp}`` があれば
     それを角丸背景に載せてアイコンにする（そのページらしさが一番出る）。
  2. テーマ色 + 頭文字: そのページの ``layout.tsx`` の ``themeColor`` を背景に、
     タイトルの頭文字を載せる（ブランドカラーが効く）。
  3. slug 由来の色 + 頭文字: 上記が無ければ slug ハッシュから決まる色。

生成物 (``public/artifacts/<slug>/``):
  - ``icon-192.png`` / ``icon-512.png`` … favicon / manifest 用
  - ``apple-touch-icon.png`` (180px) … iOS ホーム画面用

これらは ``layout.tsx`` の ``metadata.icons`` から絶対パスで参照される
（``frontend/src/app/artifacts/_seo/icon-metadata.ts`` 参照）。
アイコンを変えたい時はこの PNG を差し替えるだけでブラウザタブ・検索結果に反映される。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIR = PROJECT_ROOT / "frontend" / "public"
APP_ARTIFACTS_DIR = PROJECT_ROOT / "frontend" / "src" / "app" / "artifacts"

# 生成するサイズ。apple-touch-icon は固定 180px。
_ICON_SIZES = (192, 512)
_APPLE_SIZE = 180
_LOGO_EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg")


def _color_for_slug(slug: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(slug.encode("utf-8")).digest()
    hue = digest[0] / 255
    sat = 0.52 + (digest[1] / 255) * 0.18
    light = 0.42 + (digest[2] / 255) * 0.12
    return _hsl_to_rgb(hue, sat, light)


def _hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    def f(n: int) -> float:
        k = (n + h * 12) % 12
        a = s * min(l, 1 - l)
        return l - a * max(-1, min(k - 3, 9 - k, 1))

    return tuple(round(255 * f(n)) for n in (0, 8, 4))


def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if len(value) != 6:
        return None
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except ValueError:
        return None


def _theme_color_for_slug(slug: str) -> tuple[int, int, int]:
    """そのページの layout.tsx に themeColor があれば背景色に使う。無ければ slug 由来色。"""
    layout = APP_ARTIFACTS_DIR / slug / "layout.tsx"
    if layout.exists():
        try:
            text = layout.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"themeColor:\s*['\"]([#0-9A-Fa-f]{4,7})['\"]", text)
            if m:
                rgb = _hex_to_rgb(m.group(1))
                if rgb:
                    return rgb
        except Exception:
            pass
    return _color_for_slug(slug)


def _find_logo(slug: str) -> Path | None:
    out_dir = PUBLIC_DIR / "artifacts" / slug
    for stem in ("logo", "icon-source"):
        for ext in _LOGO_EXTENSIONS:
            candidate = out_dir / f"{stem}{ext}"
            if candidate.exists():
                return candidate
    return None


def _readable_text_color(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    luminance = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    return (17, 24, 39) if luminance > 165 else (255, 255, 255)


def _initials(title: str, slug: str) -> str:
    source = (title or slug).strip()
    if not source:
        return "A"
    words = [w for w in source.replace("_", "-").replace("—", "-").split("-") if w.strip()]
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    return source[0].upper()


def _load_font(size: int):
    from PIL import ImageFont

    for font_name in ("arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _render_text_icon(size: int, bg, fg, text):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (size, size), bg)
    draw = ImageDraw.Draw(image)
    radius = round(size * 0.2)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=bg)

    font = _load_font(round(size * (0.44 if len(text) == 1 else 0.36)))
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]), text, fill=fg, font=font)
    return image


def _render_logo_icon(size: int, bg, logo_path: Path):
    """ロゴ画像を角丸背景の中央に収める。"""
    from PIL import Image

    image = Image.new("RGB", (size, size), bg)
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception:
        return None

    # 余白を 12% 取って内側にフィット
    inner = round(size * 0.76)
    logo.thumbnail((inner, inner), Image.LANCZOS)
    x = (size - logo.width) // 2
    y = (size - logo.height) // 2
    image.paste(logo, (x, y), logo)
    return image


def _render_at(size: int, bg, fg, text, logo):
    image = None
    if logo:
        image = _render_logo_icon(size, bg, logo)
    if image is None:
        image = _render_text_icon(size, bg, fg, text)
    return image


def ensure_artifact_icons(
    slug: str,
    title: str | None = None,
    *,
    force: bool = False,
    logo_path: str | Path | None = None,
) -> dict[str, str]:
    """Create / refresh artifact icons.

    ``frontend/public/artifacts/<slug>/`` に出力する:
      - ``icon-192.png`` / ``icon-512.png`` … favicon / PWA manifest 用
      - ``apple-touch-icon.png`` (180px) … iOS ホーム画面用

    これらは各 ``artifacts/<slug>/layout.tsx`` の ``metadata.icons`` から
    絶対パスで参照される（``scripts/wire_artifact_icons.py`` が配線）。
    metadata 方式なので client/server どちらの成果物でも確実に効く。

    ``force=True`` で既存があっても作り直す（アイコン変更時に使う）。
    ``logo_path`` を渡すとそのロゴ画像を最優先で焼き込む。
    """
    slug = (slug or "").strip()
    if not slug:
        return {}

    try:
        from PIL import Image  # noqa: F401  (確認のみ)
    except Exception:
        return {}

    public_dir = PUBLIC_DIR / "artifacts" / slug
    public_dir.mkdir(parents=True, exist_ok=True)

    logo = Path(logo_path) if logo_path else _find_logo(slug)
    if logo and not logo.exists():
        logo = None

    bg = _theme_color_for_slug(slug)
    fg = _readable_text_color(bg)
    text = _initials(title or "", slug)

    # (描画サイズ, 出力先, result_key)
    targets = [
        (192, public_dir / "icon-192.png", "192"),
        (512, public_dir / "icon-512.png", "512"),
        (_APPLE_SIZE, public_dir / "apple-touch-icon.png", "apple"),
    ]

    created: dict[str, str] = {}
    for size, path, key in targets:
        if path.exists() and not force:
            created[key] = str(path)
            continue
        rendered = _render_at(size, bg, fg, text, logo)
        rendered.save(path, "PNG", optimize=True)
        created[key] = str(path)

    return created


def set_artifact_icon_from_image(slug: str, image_path: str | Path) -> dict[str, str]:
    """ユーザー/ダンが用意した画像から成果物アイコンを作り直す（チャット変更経路）。

    渡された画像を ``logo`` として保存し、全サイズを再生成する。
    """
    slug = (slug or "").strip()
    src = Path(image_path)
    if not slug or not src.exists():
        return {}

    try:
        from PIL import Image
    except Exception:
        return {}

    out_dir = PUBLIC_DIR / "artifacts" / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    # 元画像を logo.png として保存（後で再生成しても再利用できる）
    saved_logo = out_dir / "logo.png"
    try:
        Image.open(src).convert("RGBA").save(saved_logo, "PNG")
    except Exception:
        return {}

    return ensure_artifact_icons(slug, force=True, logo_path=saved_logo)
