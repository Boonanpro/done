"""Read an hCaptcha challenge from its canvas at full resolution.

The drag-the-shape puzzle is drawn as a single `<canvas>` inside hCaptcha's own
frame. There are no per-piece DOM elements, so the position of the piece and of
the drop targets cannot be queried — they only exist as pixels.

Two things follow, and together they remove the guesswork that made earlier
attempts fail:

* **Input quality.** The screenshot handed to the model is downscaled and
  JPEG-compressed, which is why shape matching scored 0.63 on a puzzle it should
  have been sure about. The canvas can be read back at its native resolution
  (typically 2x what is displayed), losslessly.

* **Coordinates.** The canvas has a fixed internal size and a fixed displayed
  size, and its frame has a measurable page offset. That gives an exact
  transform from "pixel in the extracted image" to "point to click", measured
  per call. No remembered ratio, no arithmetic by hand — the failure mode where
  the grab landed outside the piece and nothing moved simply cannot occur.

hCaptcha renders the same way wherever it is embedded, so this is not specific
to any one site.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Read the biggest canvas in this document, plus everything needed to map its
# pixels back onto the page. Returns null when the frame holds no canvas.
_CAPTURE_JS = r"""
() => {
  const canvases = [...document.querySelectorAll('canvas')];
  if (!canvases.length) return null;
  // The challenge board is the largest canvas; hCaptcha also uses tiny ones.
  let best = null, bestArea = 0;
  for (const c of canvases) {
    const r = c.getBoundingClientRect();
    const area = r.width * r.height;
    if (area > bestArea) { bestArea = area; best = c; }
  }
  if (!best || bestArea < 10000) return null;
  const rect = best.getBoundingClientRect();
  let data = null, tainted = false;
  try {
    data = best.toDataURL('image/png');
  } catch (e) {
    // Cross-origin pixels make the canvas unreadable; fall back to a screenshot.
    tainted = true;
  }
  return {
    data,
    tainted,
    canvas_w: best.width,          // internal drawing resolution
    canvas_h: best.height,
    css_w: rect.width,             // size on screen
    css_h: rect.height,
    left: rect.left,               // position within THIS frame
    top: rect.top,
  };
}
"""


class CanvasCapture(dict):
    """Captured board plus the transform back to clickable page coordinates."""

    @property
    def image(self) -> bytes:
        return self["image"]

    def to_page(self, x: float, y: float) -> tuple[float, float]:
        """Map a pixel in the captured image to a point to click on the page."""
        return (
            self["origin_x"] + x * self["scale_x"],
            self["origin_y"] + y * self["scale_y"],
        )


async def _frame_offset(page, frame) -> tuple[float, float]:
    """Where this frame sits in the top-level page.

    A point inside the frame is only clickable once its own offset is added;
    hCaptcha draws inside an iframe, so skipping this puts every click near the
    top-left corner of the window.
    """
    try:
        el = await frame.frame_element()
        box = await el.bounding_box()
        if box:
            return float(box["x"]), float(box["y"])
    except Exception:
        pass
    return 0.0, 0.0


async def capture_challenge(page) -> Optional[CanvasCapture]:
    """Find the hCaptcha challenge canvas and read it at native resolution.

    Returns None when no readable challenge canvas is present, so callers can
    fall back to the ordinary screenshot path.
    """
    from app.tools.captcha_solver import _iter_frames  # local import: avoids a cycle

    frames = await _iter_frames(page)
    for frame in frames:
        url = (getattr(frame, "url", "") or "").lower()
        # The board lives in hCaptcha's frame. Checking the URL first avoids
        # pulling large canvases from the host page (ads, charts, video).
        if "hcaptcha" not in url:
            continue
        try:
            info = await frame.evaluate(_CAPTURE_JS)
        except Exception as exc:
            logger.debug("hcaptcha canvas eval failed: %s", exc)
            continue
        if not info:
            continue
        if info.get("tainted") or not info.get("data"):
            logger.info("hcaptcha canvas is not readable (cross-origin pixels)")
            continue

        raw = base64.b64decode(str(info["data"]).split(",", 1)[-1])
        canvas_w = float(info["canvas_w"]) or 1.0
        canvas_h = float(info["canvas_h"]) or 1.0
        css_w = float(info["css_w"]) or canvas_w
        css_h = float(info["css_h"]) or canvas_h
        off_x, off_y = await _frame_offset(page, frame)

        cap = CanvasCapture({
            "image": raw,
            "canvas_w": canvas_w,
            "canvas_h": canvas_h,
            "css_w": css_w,
            "css_h": css_h,
            # canvas pixel -> CSS pixel (commonly 0.5 for a 2x board)
            "scale_x": css_w / canvas_w,
            "scale_y": css_h / canvas_h,
            # top-left of the board in page coordinates
            "origin_x": off_x + float(info["left"]),
            "origin_y": off_y + float(info["top"]),
            "frame_url": url,
        })
        logger.info(
            "hcaptcha canvas captured: %dx%d drawn, %.0fx%.0f shown, origin (%.1f, %.1f), scale %.3f",
            canvas_w, canvas_h, css_w, css_h, cap["origin_x"], cap["origin_y"], cap["scale_x"],
        )
        return cap
    return None
