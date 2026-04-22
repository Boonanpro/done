'use client';

import { useCallback, useRef } from 'react';

export interface FocalPoint {
  x: number; // 0..100
  y: number; // 0..100
}

/** 画像/動画の focal point を 2D ドラッグで決める。背景に対象画像を表示 */
export function FocalPointPad({
  value,
  onChange,
  backgroundSrc,
  aspect = 16 / 9,
}: {
  value: FocalPoint;
  onChange: (v: FocalPoint) => void;
  backgroundSrc?: string;
  aspect?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      const el = ref.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const clamp = (v: number) => Math.max(0, Math.min(100, v));
      const updateFromEvent = (evt: MouseEvent | React.MouseEvent) => {
        const x = ((evt.clientX - rect.left) / rect.width) * 100;
        const y = ((evt.clientY - rect.top) / rect.height) * 100;
        onChange({ x: clamp(x), y: clamp(y) });
      };
      updateFromEvent(e);
      const onMove = (evt: MouseEvent) => updateFromEvent(evt);
      const onUp = () => {
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
      };
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    },
    [onChange]
  );

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>focal point</span>
        <span className="font-mono text-[10px]">
          {Math.round(value.x)}% {Math.round(value.y)}%
        </span>
      </div>
      <div
        ref={ref}
        onMouseDown={handleMouseDown}
        className="relative w-full cursor-crosshair overflow-hidden rounded border border-border bg-muted"
        style={{
          aspectRatio: String(aspect),
          backgroundImage: backgroundSrc ? `url(${backgroundSrc})` : undefined,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
        }}
      >
        {/* グリッドガイド（third line） */}
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute left-1/3 top-0 h-full w-px bg-white/20" />
          <div className="absolute left-2/3 top-0 h-full w-px bg-white/20" />
          <div className="absolute left-0 top-1/3 h-px w-full bg-white/20" />
          <div className="absolute left-0 top-2/3 h-px w-full bg-white/20" />
        </div>
        <div
          className="pointer-events-none absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-primary shadow"
          style={{ left: `${value.x}%`, top: `${value.y}%` }}
        />
      </div>
    </div>
  );
}
