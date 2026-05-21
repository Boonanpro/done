"use client";

import * as React from "react";
import Image from "next/image";
import { ChevronLeft, ChevronRight } from "lucide-react";

type VehicleLabel = { en: string; ja: string };

type Props = {
  items: string[];
  labels: Record<string, VehicleLabel>;
  basePath: string;
  assetVersion: string;
};

/**
 * 中央 1 台メイン + 左右にチラ見せ + 下のサムネ列。
 * スワイプ・左右ボタン・サムネタップで切替。
 */
export function PerspectiveCarousel({ items, labels, basePath, assetVersion }: Props) {
  const [index, setIndex] = React.useState(0);
  const dragRef = React.useRef({ x: 0, accum: 0, active: false });
  const N = items.length;

  const goPrev = React.useCallback(() => setIndex((i) => (i - 1 + N) % N), [N]);
  const goNext = React.useCallback(() => setIndex((i) => (i + 1) % N), [N]);

  const onPointerDown = (e: React.PointerEvent) => {
    dragRef.current = { x: e.clientX, accum: 0, active: true };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragRef.current.active) return;
    const dx = e.clientX - dragRef.current.x;
    dragRef.current.x = e.clientX;
    dragRef.current.accum += dx;
    const threshold = 80;
    while (dragRef.current.accum >= threshold) {
      dragRef.current.accum -= threshold;
      goPrev();
    }
    while (dragRef.current.accum <= -threshold) {
      dragRef.current.accum += threshold;
      goNext();
    }
  };
  const onPointerUp = (e: React.PointerEvent) => {
    dragRef.current.active = false;
    try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId); } catch {}
  };

  const prev = (index - 1 + N) % N;
  const next = (index + 1) % N;
  const currentLabel = labels[items[index]] || { en: "", ja: "" };

  return (
    <div className="relative w-full select-none">
      {/* ステージ */}
      <div
        className="relative w-full overflow-hidden cursor-grab active:cursor-grabbing touch-pan-y h-[320px] sm:h-[520px] lg:h-[600px]"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {/* ステージライト */}
        <div
          className="absolute inset-x-0 bottom-0 h-3/4 pointer-events-none"
          style={{
            background:
              "radial-gradient(ellipse 55% 75% at 50% 95%, rgba(212,175,89,0.20) 0%, transparent 70%)",
          }}
        />
        {/* 床ライン */}
        <div
          className="absolute left-[8%] right-[8%] pointer-events-none"
          style={{
            bottom: "11%",
            height: "1px",
            background:
              "linear-gradient(90deg, transparent, rgba(212,175,89,0.45), transparent)",
          }}
        />

        {/* 左奥 (prev) */}
        <div
          key={`prev-${prev}`}
          className="absolute pointer-events-none flex items-end justify-center transition-all duration-500 ease-out"
          style={{
            left: "-3%",
            bottom: "13%",
            width: "32%",
            height: "62%",
            opacity: 0.32,
          }}
        >
          <Image
            src={`${basePath}/${items[prev]}.png?v=${assetVersion}`}
            alt=""
            width={1024}
            height={1024}
            draggable={false}
            className="max-w-full max-h-full w-auto h-auto object-contain object-bottom"
            style={{ filter: "blur(0.5px)" }}
          />
        </div>

        {/* 中央 (メイン) */}
        <div
          key={`center-${index}`}
          className="absolute pointer-events-none flex items-end justify-center transition-opacity duration-500 ease-out"
          style={{
            left: "50%",
            bottom: "11%",
            transform: "translateX(-50%)",
            width: "78%",
            height: "85%",
          }}
        >
          <Image
            src={`${basePath}/${items[index]}.png?v=${assetVersion}`}
            alt={currentLabel.ja}
            width={1024}
            height={1024}
            draggable={false}
            priority
            className="max-w-full max-h-full w-auto h-auto object-contain object-bottom drop-shadow-[0_28px_36px_rgba(0,0,0,0.55)]"
          />
        </div>

        {/* 右手前 (next) */}
        <div
          key={`next-${next}`}
          className="absolute pointer-events-none flex items-end justify-center transition-all duration-500 ease-out"
          style={{
            right: "-3%",
            bottom: "9%",
            width: "34%",
            height: "64%",
            opacity: 0.36,
          }}
        >
          <Image
            src={`${basePath}/${items[next]}.png?v=${assetVersion}`}
            alt=""
            width={1024}
            height={1024}
            draggable={false}
            className="max-w-full max-h-full w-auto h-auto object-contain object-bottom"
            style={{ filter: "blur(0.5px)" }}
          />
        </div>

        {/* 左右ナビ */}
        <button
          type="button"
          onClick={goPrev}
          aria-label="前の車種"
          className="absolute left-2 sm:left-5 top-1/2 -translate-y-1/2 z-20 flex items-center justify-center w-10 h-10 sm:w-12 sm:h-12 rounded-full bg-white/10 backdrop-blur-sm border border-white/20 text-white hover:bg-[var(--yk-gold)] hover:text-[var(--yk-navy-dark)] hover:border-[var(--yk-gold)] transition-colors"
        >
          <ChevronLeft className="h-5 w-5 sm:h-6 sm:w-6" />
        </button>
        <button
          type="button"
          onClick={goNext}
          aria-label="次の車種"
          className="absolute right-2 sm:right-5 top-1/2 -translate-y-1/2 z-20 flex items-center justify-center w-10 h-10 sm:w-12 sm:h-12 rounded-full bg-white/10 backdrop-blur-sm border border-white/20 text-white hover:bg-[var(--yk-gold)] hover:text-[var(--yk-navy-dark)] hover:border-[var(--yk-gold)] transition-colors"
        >
          <ChevronRight className="h-5 w-5 sm:h-6 sm:w-6" />
        </button>
      </div>

      {/* キャプション */}
      <div className="relative text-center mt-6 sm:mt-10 px-4">
        <div className="font-mono-data text-[10px] sm:text-xs text-[var(--yk-gold)] tracking-[0.4em] mb-2 sm:mb-3">
          {String(index + 1).padStart(2, "0")}&nbsp;&nbsp;/&nbsp;&nbsp;{String(N).padStart(2, "0")}
        </div>
        <div className="font-headline text-3xl sm:text-5xl lg:text-6xl font-black text-white tracking-tight leading-none">
          {currentLabel.ja}
        </div>
        <div className="font-mono-data text-[10px] sm:text-xs text-white/40 tracking-[0.4em] mt-3 sm:mt-4">
          {currentLabel.en}
        </div>
      </div>

      {/* サムネ列 */}
      <div className="relative mt-7 sm:mt-10 max-w-6xl mx-auto">
        <div className="overflow-x-auto px-4 sm:px-6 yk-no-scrollbar">
          <div className="flex items-center gap-2 sm:gap-3 mx-auto w-fit pb-2">
            {items.map((key, i) => {
              const active = i === index;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setIndex(i)}
                  className={`relative shrink-0 w-14 h-14 sm:w-20 sm:h-20 rounded-sm border transition-all ${
                    active
                      ? "border-[var(--yk-gold)] bg-white/[0.06] ring-1 ring-[var(--yk-gold)]/40"
                      : "border-white/15 bg-white/[0.02] opacity-55 hover:opacity-100"
                  }`}
                  aria-label={labels[key]?.ja || key}
                  aria-current={active ? "true" : undefined}
                >
                  <Image
                    src={`${basePath}/${key}.png?v=${assetVersion}`}
                    alt=""
                    width={128}
                    height={128}
                    className="w-full h-full object-contain p-1.5"
                  />
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <style>{`
        .yk-no-scrollbar { scrollbar-width: none; -ms-overflow-style: none; }
        .yk-no-scrollbar::-webkit-scrollbar { display: none; }
      `}</style>
    </div>
  );
}
