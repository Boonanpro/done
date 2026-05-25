"""Public asset helpers for DAN artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIR = PROJECT_ROOT / "frontend" / "public"


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


def _initials(title: str, slug: str) -> str:
    source = (title or slug).strip()
    if not source:
        return "A"
    words = [w for w in source.replace("_", "-").replace("—", "-").split("-") if w.strip()]
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    return source[0].upper()


def ensure_artifact_icons(slug: str, title: str | None = None) -> dict[str, str]:
    """Create deterministic PNG icons for an artifact if they do not exist."""
    slug = (slug or "").strip()
    if not slug:
        return {}

    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return {}

    out_dir = PUBLIC_DIR / "artifacts" / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    bg = _color_for_slug(slug)
    fg = (255, 255, 255)
    text = _initials(title or "", slug)
    created: dict[str, str] = {}

    for size in (192, 512):
        rel = f"/artifacts/{slug}/icon-{size}.png"
        path = out_dir / f"icon-{size}.png"
        if path.exists():
            created[str(size)] = rel
            continue

        image = Image.new("RGB", (size, size), bg)
        draw = ImageDraw.Draw(image)
        radius = round(size * 0.2)
        # Draw a rounded rectangle over a transparent-style edge by masking with
        # the same background; this keeps the PNG simple and deterministic.
        draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=bg)

        font_size = round(size * (0.44 if len(text) == 1 else 0.36))
        font = None
        for font_name in ("arialbd.ttf", "arial.ttf"):
            try:
                font = ImageFont.truetype(font_name, font_size)
                break
            except Exception:
                pass
        if font is None:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]), text, fill=fg, font=font)
        image.save(path, "PNG", optimize=True)
        created[str(size)] = rel

    return created
