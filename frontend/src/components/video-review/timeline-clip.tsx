'use client';

/**
 * タイムラインのクリップ1つ分。React.memo なので、押した・選んだ・動かしたクリップだけが描き直される
 * （以前は1つ選ぶたびに600個のクリップ全部を描き直していて、遅いPCで0.2〜0.3秒止まっていた）。
 * 押した時の処理は fns（ref）から最新の物を呼ぶので、関数が変わっても描き直さない。
 */
import { memo } from 'react';

export type ClipBoxFns = {
  startDrag: (event: React.PointerEvent, clipId: string, mode: 'start' | 'end' | 'move') => void;
  openMenu: (event: React.MouseEvent, clipId: string) => void;
  focusClip: (clipId: string) => void;
};

type Props = {
  clipId: string;
  left: number;   // % of the track
  width: number;  // % of the track
  badge: string;
  label: string;
  colorClass: string;
  thumb?: string;
  narrow: boolean;  // 画面で数ピクセルしかない時は、端のつまみと文字を描かない（部品を5分の1に）
  selected: boolean;
  linkedSelected: boolean;
  touch: boolean;
  appear: boolean;
  vanish: boolean;
  title: string;
  fns: React.MutableRefObject<ClipBoxFns>;
};

function ClipBoxInner({ clipId, left, width, badge, label, colorClass, thumb, narrow, selected, linkedSelected, touch, appear, vanish, title, fns }: Props) {
  const cls = `absolute flex cursor-grab items-center overflow-hidden rounded border bg-cover bg-center text-[10px] text-white shadow-sm active:cursor-grabbing ${colorClass} ${
    touch ? 'dan-touch' : ''} ${appear ? 'dan-appear' : ''} ${vanish ? 'dan-vanish' : ''} ${
    selected
      ? 'z-[5] border-2 border-yellow-300 ring-2 ring-yellow-300/80 brightness-125'
      : linkedSelected
        ? 'border-yellow-300/70 ring-2 ring-yellow-300/40 ring-dashed'
        : 'border-white/30'
  }`;
  const style: React.CSSProperties = {
    left: `${left}%`,
    width: `${width}%`,
    minWidth: '3px',
    top: 3,
    bottom: 3,
    ...(thumb && !narrow ? { backgroundImage: `linear-gradient(rgba(0,0,0,0.4), rgba(0,0,0,0.4)), url(${thumb})` } : {}),
  };
  if (narrow) {
    return (
      <div
        data-clip-id={clipId}
        className={cls}
        style={style}
        title={title}
        onPointerDown={(event) => fns.current.startDrag(event, clipId, 'move')}
        onDoubleClick={(event) => { event.stopPropagation(); fns.current.focusClip(clipId); }}
        onContextMenu={(event) => fns.current.openMenu(event, clipId)}
      />
    );
  }
  return (
    <div data-clip-id={clipId} className={cls} style={style} title={title} onContextMenu={(event) => fns.current.openMenu(event, clipId)}>
      <button
        type="button"
        className="h-full w-2 shrink-0 cursor-ew-resize bg-black/30"
        onPointerDown={(event) => fns.current.startDrag(event, clipId, 'start')}
        aria-label="Resize clip start"
      />
      <div
        className="flex h-full min-w-0 flex-1 cursor-grab items-center gap-1 truncate px-1 active:cursor-grabbing"
        onPointerDown={(event) => fns.current.startDrag(event, clipId, 'move')}
        onDoubleClick={(event) => { event.stopPropagation(); fns.current.focusClip(clipId); }}
      >
        <span className="shrink-0 rounded bg-black/45 px-1 text-[8px] leading-tight">{badge}</span>
        <span className="truncate">{label}</span>
      </div>
      <button
        type="button"
        className="h-full w-2 shrink-0 cursor-ew-resize bg-black/30"
        onPointerDown={(event) => fns.current.startDrag(event, clipId, 'end')}
        aria-label="Resize clip end"
      />
    </div>
  );
}

export const ClipBox = memo(ClipBoxInner);
