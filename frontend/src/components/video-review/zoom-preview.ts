/**
 * ズームの「見せるだけ」の値（2026-11-16）。
 * つまみ・Shift+ホイール・＋／－で拡大率を変えている間は、クリップを描き直さずに、タイムラインを
 * 横に引き伸ばして見せる（transform）。止めて0.25秒たつか、つまみを離した時に本当の拡大率に
 * 切り替えて描き直す。目盛りとつまみは、この値を読んで動いている間も合わせて動く。
 */
export type ZoomPreview = {
  get: () => number | null;
  set: (value: number | null) => void;
  subscribe: (fn: () => void) => () => void;
};

export function createZoomPreview(): ZoomPreview {
  let value: number | null = null;
  const subs = new Set<() => void>();
  return {
    get: () => value,
    set: (next) => {
      if (next === value) return;
      value = next;
      subs.forEach((fn) => fn());
    },
    subscribe: (fn) => {
      subs.add(fn);
      return () => { subs.delete(fn); };
    },
  };
}
