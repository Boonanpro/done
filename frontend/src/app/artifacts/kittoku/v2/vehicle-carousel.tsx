"use client";

import * as React from "react";
import Image from "next/image";

type Props = {
  items: string[];
  basePath: string;
  assetVersion: string;
};

/**
 * 回転寿司レーン風の3D楕円軌道カルーセル。
 * - 楕円軌道上を画像が等速移動
 * - 画像自体は常に正面（回転しない）
 * - 手前中央が最大スケール、奥が最小
 * - タッチ/マウスドラッグで手動回転 + 一時停止
 */
export function VehicleCarousel({ items, basePath, assetVersion }: Props) {
  const thetaRef = React.useRef(0);
  const draggingRef = React.useRef(false);
  const lastXRef = React.useRef(0);
  const itemsRef = React.useRef<(HTMLDivElement | null)[]>([]);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const [size, setSize] = React.useState({ w: 1200, h: 380 });

  // コンテナサイズに応じて軌道半径を計算
  React.useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      const w = el.clientWidth;
      const h = Math.min(w * 0.32, 380); // 画面幅に対する高さ
      setSize({ w, h });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 描画 (毎フレーム DOM操作。Stateを介さず軽量)
  React.useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const speed = 0.4; // rad/sec

    const render = () => {
      const { w, h } = size;
      const N = items.length;
      const Rx = w * 0.42;
      const Ry = h * 0.4;
      const baseSize = Math.min(w * 0.28, 360);
      const cx = w / 2;
      const cy = h / 2;

      for (let i = 0; i < N; i++) {
        const node = itemsRef.current[i];
        if (!node) continue;
        const a = thetaRef.current + (i / N) * Math.PI * 2;
        const x = Math.sin(a) * Rx;
        const y = -Math.cos(a) * Ry;
        const s = (Math.cos(a) + 1.4) / 2.4; // 0.16〜1.0
        const scale = 0.35 + s * 0.85; // 0.35〜1.2
        const half = baseSize / 2;
        const left = cx + x - half;
        const top = cy + y - half;
        node.style.transform = `translate3d(${left}px, ${top}px, 0) scale(${scale})`;
        node.style.zIndex = String(Math.round(s * 100));
        node.style.opacity = `${0.35 + s * 0.65}`;
      }
    };

    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      if (!draggingRef.current) {
        thetaRef.current += speed * dt;
      }
      render();
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [items.length, size]);

  // ドラッグ
  const onPointerDown = (e: React.PointerEvent) => {
    draggingRef.current = true;
    lastXRef.current = e.clientX;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!draggingRef.current) return;
    const dx = e.clientX - lastXRef.current;
    lastXRef.current = e.clientX;
    // 横移動 1px = 0.005 rad
    thetaRef.current -= dx * 0.005;
  };
  const onPointerUp = (e: React.PointerEvent) => {
    draggingRef.current = false;
    try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId); } catch {}
  };

  const baseSize = Math.min(size.w * 0.28, 360);

  return (
    <div
      ref={containerRef}
      className="relative w-full select-none touch-pan-y cursor-grab active:cursor-grabbing overflow-hidden"
      style={{ height: size.h }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      {items.map((item, i) => (
        <div
          key={item}
          ref={(el) => { itemsRef.current[i] = el; }}
          className="absolute left-0 top-0 will-change-transform pointer-events-none"
          style={{
            width: baseSize,
            height: baseSize,
            transformOrigin: "center center",
          }}
        >
          <Image
            src={`${basePath}/${item}.png?v=${assetVersion}`}
            alt=""
            width={Math.round(baseSize)}
            height={Math.round(baseSize)}
            draggable={false}
            className="w-full h-full object-contain"
            priority={i < 3}
          />
        </div>
      ))}
    </div>
  );
}

/**
 * 部品マーキー: 直線でループ、ドラッグで一時停止+手動スクロール可
 */
export function PartsMarquee({
  items,
  basePath,
  assetVersion,
  size = 110,
  speed = 50,
  direction = "left",
  initialCenterIndex,
}: {
  items: string[];
  basePath: string;
  assetVersion: string;
  size?: number;
  speed?: number;
  direction?: "left" | "right";
  initialCenterIndex?: number;
}) {
  const REPEAT = 6;
  const containerRef = React.useRef<HTMLDivElement>(null);
  const trackRef = React.useRef<HTMLDivElement>(null);
  const offsetRef = React.useRef(0);
  const draggingRef = React.useRef(false);
  const lastXRef = React.useRef(0);
  const initializedRef = React.useRef(false);

  // 1周期の長さ (= 1セット分のtrack幅)
  const getCycle = (): number => {
    if (!trackRef.current) return 0;
    return trackRef.current.scrollWidth / REPEAT;
  };
  const wrapOffset = (off: number, cycle: number): number => {
    if (cycle <= 0) return off;
    let v = off % cycle;
    if (v < 0) v += cycle;
    return v;
  };

  // 初期センター位置: 指定された index を画面中央に置く (1回のみ)
  React.useEffect(() => {
    if (initialCenterIndex == null) return;
    if (initializedRef.current) return;
    const trySet = () => {
      if (initializedRef.current) return true;
      if (!trackRef.current || !containerRef.current) return false;
      // 中央寄りのコピー (REPEAT の中央あたり) を使って境界からの戻り回避
      const childIdxInTrack = Math.floor(REPEAT / 2) * items.length + initialCenterIndex;
      const child = trackRef.current.children[childIdxInTrack] as HTMLElement | undefined;
      if (!child || child.offsetWidth === 0) return false;
      const itemCenter = child.offsetLeft + child.offsetWidth / 2;
      const target = itemCenter - containerRef.current.clientWidth / 2;
      const cycle = getCycle();
      const off = wrapOffset(target, cycle);
      offsetRef.current = off;
      trackRef.current.style.transform = `translateX(-${off}px)`;
      initializedRef.current = true;
      return true;
    };
    if (trySet()) return;
    const id = window.setInterval(() => { if (trySet()) window.clearInterval(id); }, 50);
    const timeoutId = window.setTimeout(() => window.clearInterval(id), 3000);
    return () => { window.clearInterval(id); window.clearTimeout(timeoutId); };
  }, [initialCenterIndex, items.length]);

  React.useEffect(() => {
    if (speed === 0) return;
    let raf = 0;
    let last = performance.now();
    const sign = direction === "right" ? -1 : 1;
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      if (!draggingRef.current && trackRef.current) {
        offsetRef.current = wrapOffset(offsetRef.current + sign * speed * dt, getCycle());
        trackRef.current.style.transform = `translateX(-${offsetRef.current}px)`;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [speed, direction]);

  const onPointerDown = (e: React.PointerEvent) => {
    draggingRef.current = true;
    lastXRef.current = e.clientX;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!draggingRef.current || !trackRef.current) return;
    const dx = e.clientX - lastXRef.current;
    lastXRef.current = e.clientX;
    offsetRef.current = wrapOffset(offsetRef.current - dx, getCycle());
    trackRef.current.style.transform = `translateX(-${offsetRef.current}px)`;
  };
  const onPointerUp = (e: React.PointerEvent) => {
    draggingRef.current = false;
    try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId); } catch {}
  };

  const repeatedItems = React.useMemo(() => {
    const out: string[] = [];
    for (let r = 0; r < REPEAT; r++) out.push(...items);
    return out;
  }, [items]);

  return (
    <div
      ref={containerRef}
      className="relative overflow-hidden select-none cursor-grab active:cursor-grabbing touch-pan-y"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      <div ref={trackRef} className="flex gap-4 sm:gap-8 w-max will-change-transform">
        {repeatedItems.map((item, i) => (
          <div
            key={`p-${i}`}
            className="shrink-0 relative"
            style={{ width: size, height: size }}
          >
            <Image
              src={`${basePath}/${item}.png?v=${assetVersion}`}
              alt=""
              fill
              sizes={`${size}px`}
              draggable={false}
              className="object-contain pointer-events-none opacity-85"
            />
          </div>
        ))}
      </div>
    </div>
  );
}
