"""
studio_recorder — 共通録画エンジン

各 studio 案件の record_*.py から import して使う再利用可能な Playwright ベース録画エンジン。

重要なルール（このエンジンが自動で守る）:
  1. 各 click/type の前に pre_pause 秒の静止を挿入（リング表示用の時間）
     → 編集ロボット側がこの間にリングを重ねる前提
  2. 各操作で対象要素の tag と bounding_box を記録
     → ズーム／リングの形を対象に合わせる判断材料
  3. 録画は滑らかなスクロールのみ（瞬間スクロール禁止）
  4. recording.json は統合フォーマット（events + mouse_trajectory + メタ情報）で出力

出力:
  - {output_dir}/f_00000.png, f_00001.png, ...  ← フレームシーケンス（カーソル合成済み）
  - {output_dir}/{name}.mp4  ← FFmpeg で密キーフレーム encode
  - {output_dir}/{name}.json  ← 統合録画データ

依存: playwright, pillow, ffmpeg (PATH)
"""
import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List


class StudioRecorder:
    def __init__(
        self,
        output_dir: str,
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
        headless: bool = True,
    ):
        self.output_dir = Path(output_dir)
        self.width = width
        self.height = height
        self.fps = fps
        self.headless = headless

        self.frame_idx = 0
        self.current_mouse: List[float] = [width / 2, height / 2]
        self.cursor_visible = True
        self.events: List[dict] = []
        self.mouse_positions: List[Tuple[float, float]] = []

        self._playwright = None
        self._browser = None
        self._page = None

    # ------------------------- lifecycle -------------------------

    async def start(self, url: Optional[str] = None):
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._page = await self._browser.new_page(viewport={"width": self.width, "height": self.height})
        if url:
            await self._page.goto(url, wait_until="networkidle")
            await asyncio.sleep(1)

    @property
    def page(self):
        """Expose the underlying Playwright page for scene-specific needs."""
        return self._page

    # ------------------------- internal frame capture -------------------------

    async def _capture(self, n: int = 1):
        for _ in range(n):
            await self._page.screenshot(path=str(self.output_dir / f"f_{self.frame_idx:05d}.png"))
            if self.cursor_visible:
                self.mouse_positions.append(tuple(self.current_mouse))
            else:
                self.mouse_positions.append((-100.0, -100.0))
            self.frame_idx += 1

    @property
    def _time(self) -> float:
        return self.frame_idx / self.fps

    # ------------------------- element helpers -------------------------

    async def _get_element(self, selector: Optional[str] = None, text: Optional[str] = None):
        if text:
            return await self._page.query_selector(f"text={text}")
        return await self._page.query_selector(selector)

    async def _get_metadata(self, el) -> dict:
        box = await el.bounding_box()
        tag = (await el.evaluate("el => el.tagName")).lower()
        label = None
        try:
            txt = await el.evaluate("el => el.innerText || el.textContent || el.value || ''")
            if txt:
                label = txt.strip()[:80]
        except Exception:
            pass
        return {
            "tag": tag,
            "bbox": (
                {
                    "x": round(box["x"], 1),
                    "y": round(box["y"], 1),
                    "w": round(box["width"], 1),
                    "h": round(box["height"], 1),
                }
                if box
                else None
            ),
            "label": label,
        }

    # ------------------------- motion primitives -------------------------

    async def _hold_still(self, seconds: float):
        """Keep cursor at current position for `seconds`. Used for pre-click ring time."""
        frames = max(1, int(seconds * self.fps))
        for _ in range(frames):
            await self._capture()

    async def _move_to(self, el, steps: int = 20) -> Optional[Tuple[float, float]]:
        box = await el.bounding_box()
        if not box:
            return None
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        sx, sy = self.current_mouse if self.current_mouse[0] >= 0 else (cx + 150, cy + 100)
        for i in range(steps):
            t = (i + 1) / steps
            t = t * t * (3 - 2 * t)
            self.current_mouse[0] = sx + (cx - sx) * t
            self.current_mouse[1] = sy + (cy - sy) * t
            await self._capture()
        return (cx, cy)

    async def _smooth_scroll_to_y(self, target_y: float, steps: int = 50, hide_cursor_during: bool = True):
        """Smooth scroll. Auto-hides cursor during transition (SKILL rule)."""
        current_y = await self._page.evaluate("window.scrollY")
        if abs(current_y - target_y) < 30:
            return
        prev_visible = self.cursor_visible
        if hide_cursor_during:
            self.cursor_visible = False
        try:
            for i in range(steps):
                t = (i + 1) / steps
                t = t * t * (3 - 2 * t)
                y = current_y + (target_y - current_y) * t
                await self._page.evaluate(f"window.scrollTo(0, {int(y)})")
                await self._capture()
        finally:
            self.cursor_visible = prev_visible

    async def _ensure_in_viewport(self, el, margin: int = 80):
        """Before any interaction: verify target is fully visible. If not, smooth-scroll.
        Prevents Playwright's instant auto-scroll from breaking the layout."""
        box = await el.bounding_box()
        if not box:
            return
        if box["y"] >= margin and box["y"] + box["height"] <= self.height - margin:
            return  # already visible with margin
        target_y = await el.evaluate("el => el.getBoundingClientRect().top + window.scrollY")
        await self._smooth_scroll_to_y(max(0, target_y - margin), steps=30)

    # ------------------------- public scene API -------------------------

    async def click(
        self,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        pre_pause: float = 0.9,
        move_steps: int = 20,
    ):
        """
        Pre-pause (ring time) → move to target → record metadata → click.
        The pre-pause holds the cursor at its current position so that an overlaid
        ring at the target has time to appear/fade BEFORE the cursor moves.
        """
        el = await self._get_element(selector, text)
        if not el:
            print(f"[recorder] WARN element not found: {selector or text}")
            return None

        # Ensure target is visible BEFORE any motion (prevents Playwright instant-scroll)
        await self._ensure_in_viewport(el)

        await self._hold_still(pre_pause)
        xy = await self._move_to(el, steps=move_steps)
        if not xy:
            return None
        cx, cy = xy

        metadata = await self._get_metadata(el)
        self.events.append(
            {
                "t": round(self._time, 3),
                "type": "click",
                "x": round(cx, 1),
                "y": round(cy, 1),
                "target": metadata,
            }
        )
        await self._page.mouse.click(cx, cy)
        await asyncio.sleep(0.1)
        await self._capture(5)
        return el

    async def type(
        self,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        value: str = "",
        pre_pause: float = 0.9,
        typing_speed: float = 0.03,
        move_steps: int = 20,
    ):
        """
        Pre-pause → move to input → click → type characters → record type event with duration.
        The type event is a single entry (not start/end pair).
        """
        el = await self._get_element(selector, text)
        if not el:
            print(f"[recorder] WARN element not found: {selector or text}")
            return None

        # Ensure target is visible BEFORE any motion (prevents Playwright instant-scroll)
        await self._ensure_in_viewport(el)

        await self._hold_still(pre_pause)
        xy = await self._move_to(el, steps=move_steps)
        if not xy:
            return None

        metadata = await self._get_metadata(el)
        box = await el.bounding_box()
        start_t = self._time

        await self._page.mouse.click(xy[0], xy[1])
        await asyncio.sleep(0.1)
        await self._capture(3)

        # Use keyboard.type (into focused element) to avoid Playwright auto-scroll
        for ch in value:
            await self._page.keyboard.type(ch)
            await asyncio.sleep(typing_speed)
            await self._capture(3)

        end_t = self._time
        self.events.append(
            {
                "t": round(start_t, 3),
                "type": "type",
                "x": round(xy[0], 1),
                "y": round(xy[1], 1),
                "duration": round(end_t - start_t, 3),
                "text": value,
                "target": metadata,
            }
        )
        await self._capture(5)
        return el

    async def select_option(
        self,
        selector: str,
        label: str,
        pre_pause: float = 0.9,
        move_steps: int = 20,
    ):
        """Dropdown selection. Recorded as a click event with select target."""
        el = await self._get_element(selector=selector)
        if not el:
            return None

        await self._ensure_in_viewport(el)
        await self._hold_still(pre_pause)
        xy = await self._move_to(el, steps=move_steps)
        if not xy:
            return None

        metadata = await self._get_metadata(el)
        self.events.append(
            {
                "t": round(self._time, 3),
                "type": "click",
                "x": round(xy[0], 1),
                "y": round(xy[1], 1),
                "target": metadata,
                "extra": {"selected_label": label},
            }
        )
        await self._page.select_option(selector, label=label)
        await asyncio.sleep(0.1)
        await self._capture(15)
        return el

    async def scroll_to(
        self,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        margin: int = 100,
        steps: int = 50,
    ):
        """Smooth scroll to an element. Cursor auto-hidden during transition."""
        el = await self._get_element(selector, text)
        if not el:
            return
        box = await el.bounding_box()
        if box and 20 <= box["y"] and box["y"] + box["height"] <= self.height - 20:
            return
        target_y = await el.evaluate("el => el.getBoundingClientRect().top + window.scrollY")
        await self._smooth_scroll_to_y(max(0, target_y - margin), steps)

    async def scroll_to_top(self, steps: int = 50):
        """Smooth scroll to top of page. Cursor auto-hidden. Use this instead of raw page.evaluate."""
        await self._smooth_scroll_to_y(0, steps)

    async def scroll_to_y(self, y: float, steps: int = 50):
        """Smooth scroll to absolute Y. Cursor auto-hidden."""
        await self._smooth_scroll_to_y(max(0, y), steps)

    async def fit_elements_in_viewport(self, selectors: List[str], margin: int = 40):
        """Scroll so all specified elements are visible in one shot, if possible.
        Cursor auto-hidden during scroll."""
        tops, bottoms = [], []
        for sel in selectors:
            el = await self._page.query_selector(sel)
            if not el:
                continue
            t = await el.evaluate("el => el.getBoundingClientRect().top + window.scrollY")
            b = await el.evaluate("el => el.getBoundingClientRect().bottom + window.scrollY")
            tops.append(t)
            bottoms.append(b)
        if not tops:
            return
        top = min(tops)
        bottom = max(bottoms)
        group_h = bottom - top
        if group_h > self.height - margin * 2:
            target_y = top - margin
        else:
            target_y = top - (self.height - group_h) / 2
        await self._smooth_scroll_to_y(max(0, target_y), steps=40)

    async def wait(self, seconds: float):
        """Explicit static hold (cursor visible, position unchanged)."""
        await self._hold_still(seconds)

    async def hide_cursor(self):
        self.cursor_visible = False

    async def show_cursor(self):
        self.cursor_visible = True

    async def go(self, url: str):
        await self._page.goto(url, wait_until="networkidle")
        await asyncio.sleep(0.5)

    # ------------------------- finalize -------------------------

    async def finalize(self, output_name: str = "recording", cursor_size: int = 28):
        """Close browser, composite cursor, write recording.json, encode MP4.
        JSON is written BEFORE encoding so data is preserved even if ffmpeg fails."""
        await self._browser.close()
        await self._playwright.stop()

        self._composite_cursor(cursor_size)

        # Write JSON first (preserves data even if ffmpeg fails)
        duration = self.frame_idx / self.fps
        recording = {
            "video": f"{output_name}.mp4",
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "duration": round(duration, 3),
            "events": self.events,
            "mouse_trajectory": {
                "fps": self.fps,
                "positions": [list(p) for p in self.mouse_positions],
            },
        }
        json_path = self.output_dir / f"{output_name}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(recording, f, ensure_ascii=False, indent=2)
        print(f"[recorder] wrote {json_path}")

        mp4_path = self.output_dir / f"{output_name}.mp4"
        self._encode_frames(mp4_path)
        print(f"[recorder] wrote {mp4_path}")
        print(f"[recorder] events={len(self.events)} frames={self.frame_idx} duration={duration:.2f}s")

    def _composite_cursor(self, size: int):
        from PIL import Image, ImageDraw
        print("[recorder] compositing cursor...")
        for i, (mx, my) in enumerate(self.mouse_positions):
            if mx < 0 or my < 0:
                continue
            path = self.output_dir / f"f_{i:05d}.png"
            if not path.exists():
                continue
            img = Image.open(path).convert("RGBA")
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            mx_i, my_i = int(mx), int(my)
            pts = [
                (mx_i, my_i),
                (mx_i, my_i + size),
                (mx_i + int(size * 0.3), my_i + int(size * 0.75)),
                (mx_i + int(size * 0.5), my_i + int(size * 1.2)),
                (mx_i + int(size * 0.65), my_i + int(size * 1.1)),
                (mx_i + int(size * 0.4), my_i + int(size * 0.65)),
                (mx_i + int(size * 0.75), my_i + int(size * 0.65)),
            ]
            for dx, dy in [(-1, -1), (1, 1), (-1, 1), (1, -1)]:
                draw.polygon([(px + dx, py + dy) for px, py in pts], fill=(0, 0, 0, 255))
            draw.polygon(pts, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
            result = Image.alpha_composite(img, overlay)
            result.convert("RGB").save(path)

    def _find_ffmpeg(self) -> str:
        """Locate ffmpeg executable. Checks PATH then common Windows install locations."""
        # PATH
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
        # Common Windows locations
        candidates = [
            r"C:\Users\Owner\ffmpeg\bin\ffmpeg.exe",
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        raise RuntimeError(
            "ffmpeg not found. Install ffmpeg and add to PATH, or place at "
            "C:/Users/Owner/ffmpeg/bin/ffmpeg.exe"
        )

    def _encode_frames(self, output_path: Path):
        ffmpeg_exe = self._find_ffmpeg()
        cmd = [
            ffmpeg_exe, "-y",
            "-framerate", str(self.fps),
            "-i", str(self.output_dir / "f_%05d.png"),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-r", str(self.fps),
            "-g", str(self.fps),
            "-keyint_min", str(self.fps),
            "-movflags", "+faststart",
            str(output_path),
        ]
        print(f"[recorder] encoding via {ffmpeg_exe}...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr[-2000:])
            raise RuntimeError("ffmpeg encoding failed")
