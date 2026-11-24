/** The pictures of the screen the owner shows in a call, kept in this page only (app/services/voice_owner_screen.py).
 * Nothing is sent while nobody needs to look; when a request in the call needs the screen (Jev's choice), the server
 * asks for a window of time and gets the pictures that were on the screen then. */

export type ScreenFrame = { at: number; jpeg: string; surface: string };

export const KEEP_MS = 90_000;   // pictures older than this go, except the one still on the screen at the window's start
export const GIVEN = 5;

/** Keep the last KEEP_MS, and the newest older one (it was on the screen when the kept time began). */
export function trim(frames: ScreenFrame[], now: number): ScreenFrame[] {
  const from = now - KEEP_MS;
  const firstKept = frames.findIndex(f => f.at >= from);
  if (firstKept < 0) return frames.slice(-1);
  return frames.slice(Math.max(0, firstKept - 1));
}

/** The pictures on the screen between start and end (ms, this page's clock), oldest first, at most GIVEN: the one that
 * was on the screen at start, and those that came during the window. When more, the first and last are kept and the
 * rest spread evenly. */
export function during(frames: ScreenFrame[], start: number, end: number, given = GIVEN): ScreenFrame[] {
  let onAtStart = -1;
  frames.forEach((f, i) => { if (f.at <= start) onAtStart = i; });
  const picked = frames.filter((f, i) => i === onAtStart || (f.at > start && f.at <= end));
  if (!picked.length && frames.length && frames[0].at <= end) return [frames[0]];
  if (picked.length <= given) return picked;
  const out: ScreenFrame[] = [];
  for (let k = 0; k < given; k += 1) out.push(picked[Math.round(k * (picked.length - 1) / (given - 1))]);
  return out.filter((f, i) => out.indexOf(f) === i);
}

/** How different two small grey thumbnails are (0..1), to keep a picture only when the screen changed. */
export function difference(a: Uint8ClampedArray | null, b: Uint8ClampedArray): number {
  if (!a || a.length !== b.length) return 1;
  let sum = 0;
  for (let i = 0; i < a.length; i += 4) sum += Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]);
  return sum / (a.length / 4 * 3 * 255);
}
