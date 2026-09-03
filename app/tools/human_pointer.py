"""Human-like pointer movement for anti-bot challenges.

hCaptcha (and Talon, Epic's wrapper around it) scores *how* the pointer behaves,
not only whether the answer is right. A programmatic click teleports: one event
at the target with no approach, no curve, no speed change, and no dwell. That
reads as automation even when the answer is correct — which is exactly the
"回答は成立しているのに『誤った返答』で弾かれる" symptom.

This module replaces teleports with a plausible hand movement:

  * a curved path (quadratic Bezier with a random control point) instead of a
    straight line — real arms overshoot and arc, they do not travel on rails
  * ease-in/ease-out speed, so the pointer accelerates away and decelerates onto
    the target rather than moving at a constant rate
  * sub-pixel jitter along the way, and a small settle wobble at the end
  * randomised dwell before pressing and before releasing

Nothing here guarantees a pass — behavioural scoring is a moving target — but it
removes the signals that are trivially machine-detectable.

All timings are randomised per call; two identical requests never replay the
same trace.
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Deliberately generous: a human takes a noticeable fraction of a second to
# cross a dialog, and finishing in 20ms is itself a bot signal.
_MIN_STEPS = 18
_MAX_STEPS = 46


def _ease(t: float) -> float:
    """Ease-in-out. Slow at both ends, fastest in the middle."""
    return 3 * t * t - 2 * t * t * t


def _bezier_point(p0, p1, p2, t: float) -> tuple[float, float]:
    u = 1 - t
    x = u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0]
    y = u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]
    return x, y


def _control_point(start, end) -> tuple[float, float]:
    """Pick an off-axis control point so the path bows instead of running straight."""
    mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
    dx, dy = end[0] - start[0], end[1] - start[1]
    dist = math.hypot(dx, dy) or 1.0
    # perpendicular offset, scaled to the distance travelled
    nx, ny = -dy / dist, dx / dist
    bow = random.uniform(0.06, 0.18) * dist * random.choice((-1, 1))
    return mx + nx * bow, my + ny * bow


def path_points(
    start: tuple[float, float],
    end: tuple[float, float],
    steps: Optional[int] = None,
) -> list[tuple[float, float]]:
    """Build the intermediate points of one human-ish movement."""
    dist = math.hypot(end[0] - start[0], end[1] - start[1])
    if steps is None:
        steps = int(min(_MAX_STEPS, max(_MIN_STEPS, dist / 12)))
    ctrl = _control_point(start, end)
    pts: list[tuple[float, float]] = []
    for i in range(1, steps + 1):
        t = _ease(i / steps)
        x, y = _bezier_point(start, ctrl, end, t)
        if i < steps:
            # hand tremor; kept sub-pixel-ish so the path stays believable
            x += random.uniform(-1.2, 1.2)
            y += random.uniform(-1.2, 1.2)
        pts.append((x, y))
    return pts


class HumanPointer:
    """Drives a page's mouse along believable paths.

    Works with the executor page proxy and with a real Playwright page: both
    expose ``mouse.move/down/up``.
    """

    def __init__(self, page: Any):
        self._page = page
        self._mouse = page.mouse
        # Where we believe the cursor is. Starting somewhere arbitrary beats
        # starting at (0,0), which would make every first move originate from
        # the same corner.
        self._pos: tuple[float, float] = (
            random.uniform(120, 640),
            random.uniform(120, 480),
        )

    @property
    def position(self) -> tuple[float, float]:
        return self._pos

    async def move_to(self, x: float, y: float, steps: Optional[int] = None) -> None:
        for px, py in path_points(self._pos, (x, y), steps):
            await self._mouse.move(px, py)
            await asyncio.sleep(random.uniform(0.004, 0.017))
        self._pos = (x, y)

    async def click(self, x: float, y: float) -> None:
        await self.move_to(x, y)
        # settle: a hand does not stop dead on the pixel it clicks
        await self._settle()
        await asyncio.sleep(random.uniform(0.05, 0.16))
        await self._mouse.down()
        await asyncio.sleep(random.uniform(0.045, 0.13))  # press duration
        await self._mouse.up()
        await asyncio.sleep(random.uniform(0.12, 0.35))

    async def drag(self, sx: float, sy: float, tx: float, ty: float) -> None:
        """Press at the source, travel, release on the target.

        The pause after pressing matters: challenges that watch for "grabbed and
        teleported in the same frame" reject an instantaneous drag.
        """
        await self.move_to(sx, sy)
        await self._settle()
        await asyncio.sleep(random.uniform(0.08, 0.2))
        await self._mouse.down()
        await asyncio.sleep(random.uniform(0.09, 0.22))
        # carry the object over a curve, slower than a bare pointer move
        for px, py in path_points((sx, sy), (tx, ty)):
            await self._mouse.move(px, py)
            await asyncio.sleep(random.uniform(0.008, 0.026))
        self._pos = (tx, ty)
        await self._settle()
        await asyncio.sleep(random.uniform(0.1, 0.26))
        await self._mouse.up()
        await asyncio.sleep(random.uniform(0.15, 0.4))

    async def _settle(self) -> None:
        """Tiny corrective wobble on arrival, like a hand finding the target."""
        x, y = self._pos
        for _ in range(random.randint(1, 3)):
            await self._mouse.move(
                x + random.uniform(-1.6, 1.6), y + random.uniform(-1.6, 1.6)
            )
            await asyncio.sleep(random.uniform(0.012, 0.038))
        await self._mouse.move(x, y)
