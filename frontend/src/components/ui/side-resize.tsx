'use client';

// 右に常にいる会話の欄と、左の表示の境目を引いて幅を変える部品（2026-11-21 本人「チャットと左側の表示領域はドラッグアンドドロップで
// 可変にする」。会話の欄を作る時の決まり）。
// - const [ref, side] = useSideWidth(...)。欄（aside など）に ref と style={side.style} を付け、幅は CSS の var(--side-w) で決める（例: lg:w-[var(--side-w)]）。
//   その左の端に <SideResizeHandle> を置く。スマホの下から出す形などでは var を使わなければ幅は効かない。
// - 引きずっている間は React を通さず欄の幅だけを直接変える（重い左の画面を描き直さない）。離した時に幅を覚える（端末ごと）。
// - ダブルクリックで最初の幅に戻す。
import { useCallback, useRef, useState } from 'react';

import { cn } from '@/lib/utils';

export type SideWidth = {
  width: number;
  resizing: boolean;
  style: React.CSSProperties;
  startResize: (event: React.PointerEvent<HTMLElement>) => void;
  reset: () => void;
};

/** 右の欄の幅。key は端末に覚える名前、min は px、maxShare は親の幅に対する上限の割合。返すのは [欄に付ける ref, 幅の状態] */
export function useSideWidth(key: string, initial: number, min = 280, maxShare = 0.7): [React.RefObject<HTMLElement | null>, SideWidth] {
  const ref = useRef<HTMLElement | null>(null);
  // 覚えている幅は最初の描画から使う（開いてから幅が跳ねない）。この部品は画面の中でだけ動く（'use client' の画面から使う）
  const [width, setWidth] = useState(() => {
    if (typeof window === 'undefined') return initial;
    try {
      const saved = Number(localStorage.getItem(key));
      return saved >= min ? Math.round(Math.min(saved, Math.max(min, window.innerWidth * maxShare))) : initial;
    } catch { return initial; }
  });
  const [resizing, setResizing] = useState(false);
  const limit = useCallback((w: number) => {
    const parent = ref.current?.parentElement;
    const room = parent ? parent.getBoundingClientRect().width : typeof window === 'undefined' ? 1600 : window.innerWidth;
    return Math.round(Math.min(Math.max(min, room * maxShare), Math.max(min, w)));
  }, [min, maxShare]);
  const startResize = useCallback((event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const el = ref.current;
    if (!el) return;
    const startX = event.clientX;
    const startW = el.getBoundingClientRect().width;
    let next = startW;
    let raf = 0;
    const handle = event.currentTarget;
    const pid = event.pointerId;
    // つかんだ印の上に指を留める（会話や絵の上に来ても引きずりが切れない）
    try { handle.setPointerCapture(pid); } catch { /* 古いブラウザ */ }
    setResizing(true);
    const move = (ev: PointerEvent) => {
      next = limit(startW + (startX - ev.clientX));
      if (!raf) raf = requestAnimationFrame(() => { raf = 0; el.style.setProperty('--side-w', `${next}px`); });
    };
    const up = () => {
      try { handle.releasePointerCapture(pid); } catch { /* もう離れている */ }
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
      if (raf) cancelAnimationFrame(raf);
      el.style.setProperty('--side-w', `${next}px`);
      setResizing(false);
      if (Math.abs(next - startW) < 1) return;   // 押しただけ（ダブルクリックの1回目など）は覚え直さない
      setWidth(next);
      try { localStorage.setItem(key, String(next)); } catch { /* 覚えられなくても幅は変わる */ }
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
  }, [key, limit]);
  const reset = useCallback(() => {
    const w = limit(initial);
    ref.current?.style.setProperty('--side-w', `${w}px`);
    setWidth(w);
    try { localStorage.removeItem(key); } catch { /* 無くてもよい */ }
  }, [initial, key, limit]);
  const style = { ['--side-w' as string]: `${width}px` } as React.CSSProperties;
  return [ref, { width, resizing, style, startResize, reset }];
}

/** 欄の左の端に置く、引きずる所。親は position: relative にする */
export function SideResizeHandle({ side, className }: { side: SideWidth; className?: string }) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="会話の欄の幅を変える"
      title="引きずって幅を変える（ダブルクリックで元の幅）"
      onPointerDown={side.startResize}
      onDoubleClick={side.reset}
      className={cn('group absolute -left-1.5 top-0 z-20 h-full w-3 cursor-col-resize touch-none select-none', className)}
    >
      <div className={cn('absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 transition-colors',
        side.resizing ? 'bg-amber-500' : 'bg-transparent group-hover:bg-amber-400/70')} />
    </div>
  );
}
