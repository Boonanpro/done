'use client';

// サムネを描く1つの部品。エディターの画面と書き出し（/thumbnail-frame）の両方がこれで描くので、画面で見た物と
// 書き出した PNG は同じになる。中身は1枚の SVG（viewBox = サムネの画素）。部品は配列の順に奥から手前へ。
// 文字は本物の文字（SVG の text）で、縁は丸い角の stroke を文字の後ろに描き、影は縁ごとぼかした黒。
// 元のサムネ（Python の PIL で描いていた）と同じ書体・縁・影の付け方にそろえてある。

import { forwardRef, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';

import { thumbFont, type ThumbDoc, type ThumbMark, type ThumbPart, type ThumbTextPart } from './thumb-doc';

export type PartBox = { x: number; y: number; w: number; h: number };

function lines(p: ThumbTextPart) {
  return String(p.text ?? '').split('\n');
}

export function textLineHeight(p: ThumbTextPart) {
  return p.line_height || Math.round(p.size * 1.25);
}

function TextPart({ p, onMeasure }: { p: ThumbTextPart; onMeasure?: (id: string, box: PartBox, widths: number[]) => void }) {
  const f = thumbFont(p.font);
  const ref = useRef<SVGTextElement>(null);
  const [widths, setWidths] = useState<number[] | null>(null);
  const ls = lines(p);
  const lh = textLineHeight(p);
  const sw = Math.max(0, p.stroke_width || 0);
  // 外の縁（二重の縁の外側。11/20 中村さんのサムネ「白と黒の二重の縁」）。内の縁より太い時だけ見える
  const ow = Math.max(0, p.outline_width || 0);
  const pad = Math.max(sw, ow);
  const key = `${p.text}|${p.font}|${p.size}|${p.letter_spacing}|${lh}`;
  // 文字の幅（背景の札の大きさと、選んだ時の枠に使う）。書体が読み終わった時にも測り直す
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const spans = Array.from(el.querySelectorAll('tspan'));
      const ws = spans.map((s) => { try { return s.getComputedTextLength(); } catch { return 0; } });
      setWidths((prev) => (prev && prev.length === ws.length && prev.every((v, i) => Math.abs(v - ws[i]) < 0.01) ? prev : ws));
      if (onMeasure) {
        try {
          const b = el.getBBox();
          let x0 = b.x - pad, y0 = b.y - pad, x1 = b.x + b.width + pad, y1 = b.y + b.height + pad;
          if (p.bg) {
            const mw = Math.max(0, ...ws);
            x0 = Math.min(x0, p.x - p.bg.left); y0 = Math.min(y0, p.y - p.bg.top);
            x1 = Math.max(x1, p.x + mw + p.bg.right); y1 = Math.max(y1, p.y + (ls.length - 1) * lh + p.bg.bottom);
          }
          onMeasure(p.id, { x: x0, y: y0, w: x1 - x0, h: y1 - y0 }, ws);
        } catch { /* 隠れている時は測れない */ }
      }
    };
    measure();
    let stop = false;
    void document.fonts?.ready.then(() => { if (!stop) measure(); });
    const onFonts = () => measure();
    document.fonts?.addEventListener?.('loadingdone', onFonts);
    return () => { stop = true; document.fonts?.removeEventListener?.('loadingdone', onFonts); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, p.x, p.y, pad, p.id, p.bg?.left, p.bg?.right, p.bg?.top, p.bg?.bottom]);

  const shadow = p.shadow;
  const filterId = shadow ? `ts_${p.id}` : undefined;
  const maxW = widths ? Math.max(0, ...widths) : 0;
  return (
    <>
      {filterId ? (
        <defs>
          <filter id={filterId} x="-30%" y="-60%" width="160%" height="220%" colorInterpolationFilters="sRGB">
            <feGaussianBlur in="SourceAlpha" stdDeviation={shadow!.blur ?? 12} result="b" />
            <feOffset in="b" dx={shadow!.dx ?? 0} dy={shadow!.dy ?? 0} result="o" />
            <feFlood floodColor={shadow!.color || '#000'} floodOpacity={shadow!.opacity ?? 0.75} />
            <feComposite in2="o" operator="in" result="s" />
            <feMerge><feMergeNode in="s" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
      ) : null}
      {p.bg && widths ? (
        <rect
          x={p.x - p.bg.left}
          y={p.y - p.bg.top}
          width={maxW + p.bg.left + p.bg.right}
          height={(ls.length - 1) * lh + p.bg.top + p.bg.bottom}
          rx={p.bg.radius || 0}
          fill={p.bg.color}
        />
      ) : null}
      {ow > 0 ? (
        <text
          aria-hidden
          x={p.x}
          y={p.y}
          fontFamily={`"${f.family}", "NotoSansJP", sans-serif`}
          fontWeight={f.weight}
          fontSize={p.size}
          fill={p.outline || '#000'}
          stroke={p.outline || '#000'}
          strokeWidth={ow * 2}
          strokeLinejoin="round"
          strokeLinecap="round"
          paintOrder="stroke"
          filter={filterId ? `url(#${filterId})` : undefined}
          style={{ letterSpacing: `${p.letter_spacing || 0}px`, fontKerning: 'none', whiteSpace: 'pre', userSelect: 'none' }}
        >
          {ls.map((t, i) => (
            <tspan key={i} x={p.x} y={p.y + i * lh}>{t || ' '}</tspan>
          ))}
        </text>
      ) : null}
      <text
        ref={ref}
        x={p.x}
        y={p.y}
        fontFamily={`"${f.family}", "NotoSansJP", sans-serif`}
        fontWeight={f.weight}
        fontSize={p.size}
        fill={p.fill}
        stroke={sw > 0 ? (p.stroke || '#000') : undefined}
        strokeWidth={sw > 0 ? sw * 2 : undefined}
        strokeLinejoin="round"
        strokeLinecap="round"
        paintOrder="stroke"
        filter={filterId && ow <= 0 ? `url(#${filterId})` : undefined}
        style={{ letterSpacing: `${p.letter_spacing || 0}px`, fontKerning: 'none', whiteSpace: 'pre', userSelect: 'none' }}
      >
        {ls.map((t, i) => (
          <tspan key={i} x={p.x} y={p.y + i * lh}>{t || ' '}</tspan>
        ))}
      </text>
    </>
  );
}

export function partCenter(p: ThumbPart, box?: PartBox): [number, number] {
  if (p.type === 'image') return [p.x + p.w / 2, p.y + p.h / 2];
  if (box) return [box.x + box.w / 2, box.y + box.h / 2];
  return [p.x, p.y];
}

type Props = {
  doc: ThumbDoc;
  width?: number | string;        // 画面に出す幅（既定は 100%）
  marks?: ThumbMark[];
  onImageState?: (loaded: number, total: number) => void;
  onMeasure?: (id: string, box: PartBox) => void;
  boxes?: Record<string, PartBox>;
  partProps?: (p: ThumbPart) => Record<string, unknown>;
  overlay?: ReactNode;            // 選んだ部品の枠など（同じ座標で上に描く）
  style?: React.CSSProperties;
  className?: string;
  /** 見せる範囲（既定はサムネ全体）。部品の一覧の小さな絵で、その部品の所だけを見せる */
  view?: PartBox;
  onPointerDown?: React.PointerEventHandler<SVGSVGElement>;
  onPointerMove?: React.PointerEventHandler<SVGSVGElement>;
  onPointerUp?: React.PointerEventHandler<SVGSVGElement>;
  onPointerCancel?: React.PointerEventHandler<SVGSVGElement>;
  onContextMenu?: React.MouseEventHandler<SVGSVGElement>;
};

export const ThumbCanvas = forwardRef<SVGSVGElement, Props>(function ThumbCanvas(
  { doc, width = '100%', marks, onImageState, onMeasure, boxes, partProps, overlay, style, className, view, ...handlers }, ref,
) {
  const images = doc.parts.filter((p) => p.type === 'image' && !p.hidden);
  const loadedRef = useRef(new Set<string>());
  const srcKey = images.map((p) => (p as { src: string }).src).join('|');
  useEffect(() => {
    // 絵の数が変わったら数え直す（書き出しは全部読めるまで待つ）
    const keep = new Set(images.map((p) => (p as { src: string }).src));
    for (const s of [...loadedRef.current]) if (!keep.has(s)) loadedRef.current.delete(s);
    onImageState?.(loadedRef.current.size, keep.size);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [srcKey]);
  // 部品はサムネの枠で切る。選んだ枠とつまみ（overlay）だけは枠の外にもはみ出して描き、押せるようにする 2026-11-24
  const clipId = `thumbclip${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const done = (src: string) => {
    loadedRef.current.add(src);
    onImageState?.(loadedRef.current.size, new Set(images.map((p) => (p as { src: string }).src)).size);
  };

  return (
    <svg
      ref={ref}
      viewBox={view ? `${view.x} ${view.y} ${view.w} ${view.h}` : `0 0 ${doc.width} ${doc.height}`}
      width={width}
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      {...handlers}
      style={{ display: 'block', overflow: 'visible', background: doc.background || '#111', aspectRatio: view ? `${view.w} / ${view.h}` : `${doc.width} / ${doc.height}`, ...style }}
    >
      <defs><clipPath id={clipId}><rect x={0} y={0} width={doc.width} height={doc.height} /></clipPath></defs>
      <g clipPath={`url(#${clipId})`}>
      {doc.parts.map((p) => {
        if (p.hidden) return null;
        const rot = p.rotation || 0;
        const [cx, cy] = partCenter(p, boxes?.[p.id]);
        const extra = partProps?.(p) || {};
        if (p.type === 'image') {
          const flip = p.flip_x ? `translate(${2 * p.x + p.w} 0) scale(-1 1)` : '';
          return (
            <g key={p.id} data-part-id={p.id} opacity={p.opacity ?? 1} transform={rot ? `rotate(${rot} ${cx} ${cy})` : undefined} {...extra}>
              <image
                href={p.src}
                x={p.x}
                y={p.y}
                width={p.w}
                height={p.h}
                preserveAspectRatio="none"
                transform={flip || undefined}
                onLoad={() => done(p.src)}
                onError={() => done(p.src)}
                style={{ imageRendering: 'auto' }}
              />
            </g>
          );
        }
        return (
          <g key={p.id} data-part-id={p.id} opacity={p.opacity ?? 1} transform={rot ? `rotate(${rot} ${cx} ${cy})` : undefined} {...extra}>
            <TextPart p={p} onMeasure={onMeasure ? (id, box) => onMeasure(id, box) : undefined} />
          </g>
        );
      })}
      {marks?.map((m, i) => (
        <polyline
          key={`m${i}`}
          points={m.points.map(([x, y]) => `${x},${y}`).join(' ')}
          fill="none"
          stroke={m.color}
          strokeWidth={m.width}
          strokeLinecap="round"
          strokeLinejoin="round"
          pointerEvents="none"
        />
      ))}
      </g>
      {overlay}
    </svg>
  );
});

/** 部品の見せる範囲: その部品の枠（回転も含む）をサムネの枠で切った所。枠の外に全部出ている時は部品の枠のまま */
export function partView(doc: ThumbDoc, p: ThumbPart, box: PartBox): PartBox {
  let { x, y, w, h } = box;
  const rot = ((p.rotation || 0) * Math.PI) / 180;
  if (rot) {
    const [cx, cy] = partCenter(p, box);
    const pts = [[x, y], [x + w, y], [x, y + h], [x + w, y + h]].map(([px, py]) => [
      cx + (px - cx) * Math.cos(rot) - (py - cy) * Math.sin(rot),
      cy + (px - cx) * Math.sin(rot) + (py - cy) * Math.cos(rot),
    ]);
    const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]);
    x = Math.min(...xs); y = Math.min(...ys); w = Math.max(...xs) - x; h = Math.max(...ys) - y;
  }
  const x0 = Math.max(0, x), y0 = Math.max(0, y), x1 = Math.min(doc.width, x + w), y1 = Math.min(doc.height, y + h);
  if (x1 - x0 >= 4 && y1 - y0 >= 4) { x = x0; y = y0; w = x1 - x0; h = y1 - y0; }
  const pad = Math.max(w, h) * 0.04;
  return { x: x - pad, y: y - pad, w: w + pad * 2, h: h + pad * 2 };
}

// 透けている所が分かる市松模様（部品の一覧の小さな絵の下地）
const CHECKER = 'repeating-conic-gradient(rgba(255,255,255,0.14) 0% 25%, transparent 0% 50%) 50% / 10px 10px, #2a2a2a';

/** 部品1つだけを、その部品の所だけ切り取って描く小さな絵（部品の一覧・右クリックの一覧・選んだ部品の欄）。
 *  2026-11-24 本人「どんなパーツかをテキストで表すんじゃなくて、全部にサムネをつけて。見ただけで分かるように」 */
export function PartPreview({ doc, part, box, className }: { doc: ThumbDoc; part: ThumbPart; box: PartBox; className?: string }) {
  const one: ThumbDoc = { ...doc, background: 'transparent', parts: [{ ...part, hidden: false, opacity: Math.max(0.35, part.opacity ?? 1) } as ThumbPart] };
  return (
    <span className={`pointer-events-none block overflow-hidden rounded-sm ${className || ''}`} style={{ background: CHECKER }} data-part-preview={part.id}>
      <ThumbCanvas doc={one} view={partView(doc, part, box)} width="100%" style={{ width: '100%', height: '100%', aspectRatio: 'auto', background: 'transparent', overflow: 'hidden' }} />
    </span>
  );
}
