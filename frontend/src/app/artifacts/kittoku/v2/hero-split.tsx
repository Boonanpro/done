"use client";

import * as React from "react";
import Image from "next/image";

type VehicleLabel = { en: string; ja: string };

type Props = {
  videoSrc: string;
  videoPoster: string;
  mobileVideoSrc: string;
  mobileVideoPoster: string;
  vehicles: string[];
  vehiclesBasePath: string;
  assetVersion: string;
  sceneCutPoints: number[];
  vehicleLabels: Record<string, VehicleLabel>;
};

/**
 * ヒーロー領域のコンテンツ:
 *  - 動画は背景全面 (画面横幅いっぱい)
 *  - 中央コンテナ max-w-7xl の左にメインコピー (親側で配置)、 右下に車スライダー + ラベル
 *  - 動画のシーン境界に合わせて車が切替、 指で左右にドラッグしても切替
 */
export function HeroSplit({
  videoSrc,
  videoPoster,
  mobileVideoSrc,
  mobileVideoPoster,
  vehicles,
  vehiclesBasePath,
  assetVersion,
  sceneCutPoints,
  vehicleLabels,
}: Props) {
  const videoRef = React.useRef<HTMLVideoElement>(null);
  const dragRef = React.useRef({ x: 0, accum: 0, active: false });
  const [isMobile, setIsMobile] = React.useState<boolean | null>(null);
  const [vehicleIndex, setVehicleIndex] = React.useState(0);

  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(max-width: 639px)");
    const update = () => setIsMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  const activeSrc = isMobile ? mobileVideoSrc : videoSrc;
  const activePoster = isMobile ? mobileVideoPoster : videoPoster;

  React.useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const tryPlay = () => {
      const p = v.play();
      if (p && typeof p.catch === "function") p.catch(() => { /* ignore */ });
    };
    if (v.readyState >= 2) tryPlay();
    else v.addEventListener("loadeddata", tryPlay, { once: true });
  }, [activeSrc]);

  React.useEffect(() => {
    const v = videoRef.current;
    if (!v) return;

    const points = [...sceneCutPoints].sort((a, b) => a - b);
    const segmentsPerLoop = points.length + 1;

    let lastSegment = -1;
    let globalSegmentCounter = 0;
    let cancelled = false;
    let prevTime = 0;

    type WithVFC = HTMLVideoElement & {
      requestVideoFrameCallback?: (cb: (now: number, meta: { mediaTime: number }) => void) => number;
    };
    const vfc = (v as WithVFC).requestVideoFrameCallback?.bind(v);

    const segmentAt = (t: number): number => {
      let idx = 0;
      for (let i = 0; i < points.length; i++) {
        if (t >= points[i]) idx = i + 1;
        else break;
      }
      return idx;
    };

    const update = (t: number) => {
      if (cancelled) return;
      if (t + 0.5 < prevTime) {
        globalSegmentCounter += segmentsPerLoop - lastSegment;
        lastSegment = -1;
      }
      prevTime = t;
      const seg = segmentAt(t);
      if (seg !== lastSegment) {
        if (lastSegment >= 0) {
          globalSegmentCounter += seg - lastSegment;
          if (globalSegmentCounter < 0) globalSegmentCounter = 0;
        }
        lastSegment = seg;
        setVehicleIndex(globalSegmentCounter % vehicles.length);
      }
    };

    const tick = () => {
      if (cancelled) return;
      update(v.currentTime);
      if (vfc) vfc(() => tick());
      else requestAnimationFrame(tick);
    };
    tick();

    return () => { cancelled = true; };
  }, [sceneCutPoints, vehicles.length]);

  const currentVehicle = vehicles[vehicleIndex];
  const currentLabel = vehicleLabels[currentVehicle] || { en: "", ja: "" };

  return (
    <>
      {/* 動画 (背景全面、画面横幅いっぱい) */}
      <video
        key={activeSrc}
        ref={videoRef}
        className="absolute inset-0 w-full h-full object-cover"
        src={activeSrc}
        poster={activePoster}
        autoPlay
        loop
        muted
        playsInline
        preload="auto"
        aria-label="吉川特装 整備風景"
      />

      {/* 暗化グラデ: 左上(文字)と右下(車)だけにラジアル。中央は動画そのままの色 */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: [
            "radial-gradient(ellipse 55% 45% at 18% 18%, rgba(11,18,40,0.88) 0%, rgba(11,18,40,0.55) 35%, rgba(11,18,40,0.2) 60%, transparent 80%)",
            "radial-gradient(ellipse 45% 50% at 82% 80%, rgba(11,18,40,0.88) 0%, rgba(11,18,40,0.55) 35%, rgba(11,18,40,0.2) 60%, transparent 80%)",
          ].join(", "),
        }}
      />

      {/* 中央コンテナ (max-w-7xl) — 車 + ラベルを揃える */}
      <div className="absolute inset-0 pointer-events-none flex justify-center">
        <div className="relative w-full max-w-7xl px-4 sm:px-8">
          {/* 車wrapper (中央コンテナの右下) */}
          <div
            className="absolute inset-y-0 right-4 sm:right-8 w-[70%] sm:w-[28%] pointer-events-auto cursor-grab active:cursor-grabbing touch-pan-y"
            onPointerDown={(e) => {
              dragRef.current = { x: e.clientX, accum: 0, active: true };
              (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
            }}
            onPointerMove={(e) => {
              if (!dragRef.current.active) return;
              const dx = e.clientX - dragRef.current.x;
              dragRef.current.x = e.clientX;
              dragRef.current.accum += dx;
              const threshold = 60;
              while (dragRef.current.accum <= -threshold) {
                dragRef.current.accum += threshold;
                setVehicleIndex((i) => (i + 1) % vehicles.length);
              }
              while (dragRef.current.accum >= threshold) {
                dragRef.current.accum -= threshold;
                setVehicleIndex((i) => (i - 1 + vehicles.length) % vehicles.length);
              }
            }}
            onPointerUp={(e) => {
              dragRef.current.active = false;
              try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId); } catch {}
            }}
            onPointerCancel={(e) => {
              dragRef.current.active = false;
              try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId); } catch {}
            }}
          >
            {vehicles.map((v, i) => (
              <div
                key={v}
                className={`absolute inset-x-0 bottom-0 flex items-end justify-end transition-opacity duration-700 pointer-events-none ${
                  i === vehicleIndex ? "opacity-100" : "opacity-0"
                }`}
                aria-hidden={i !== vehicleIndex}
              >
                <Image
                  src={`${vehiclesBasePath}/${v}.png?v=${assetVersion}`}
                  alt=""
                  width={1024}
                  height={1024}
                  priority={i < 3}
                  draggable={false}
                  className="w-[97%] h-auto object-contain object-bottom drop-shadow-[0_22px_60px_rgba(0,0,0,0.9)] select-none"
                />
              </div>
            ))}
          </div>

          {/* 車種ラベル (車の上、右側) */}
          <div className="absolute bottom-[28%] sm:bottom-[30%] right-4 sm:right-8 text-right z-10 pointer-events-none">
            <div className="font-mono-data text-[8px] sm:text-[10px] text-[var(--yk-gold)] tracking-[0.35em] mb-1">
              {String(vehicleIndex + 1).padStart(2, "0")} / {String(vehicles.length).padStart(2, "0")}
            </div>
            <div className="font-headline text-base sm:text-2xl lg:text-3xl font-bold text-white tracking-wide leading-none drop-shadow-[0_2px_10px_rgba(0,0,0,0.9)]">
              {currentLabel.ja}
            </div>
            <div className="font-mono-data text-[8px] sm:text-[10px] text-white/45 tracking-[0.35em] mt-1">
              {currentLabel.en}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
