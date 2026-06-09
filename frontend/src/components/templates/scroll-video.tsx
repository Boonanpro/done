"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export type ScrollVideoChapter = {
  start: number;
  end: number;
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  body?: React.ReactNode;
};

type ScrollVideoProps = React.HTMLAttributes<HTMLElement> & {
  src: string;
  poster: string;
  mobileSrc?: string;
  mobilePoster?: string;
  chapters: ScrollVideoChapter[];
  heightVh?: number;
  darken?: number;
  minHeightClass?: string;
  progressBar?: boolean;
  fallback?: React.ReactNode;
  videoLabel?: string;
};

function clamp(value: number, min = 0, max = 1) {
  return Math.min(Math.max(value, min), max);
}

function usePrefersReducedMotion() {
  const [reduced, setReduced] = React.useState(false);

  React.useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return reduced;
}

function useMobileMediaQuery() {
  const [isMobile, setIsMobile] = React.useState(false);

  React.useEffect(() => {
    const query = window.matchMedia("(max-width: 639px)");
    const update = () => setIsMobile(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return isMobile;
}

export function ScrollVideo({
  src,
  poster,
  mobileSrc,
  mobilePoster,
  chapters,
  heightVh = 360,
  darken = 35,
  minHeightClass = "min-h-screen",
  progressBar = true,
  fallback,
  videoLabel = "Scroll controlled video",
  className,
  ...props
}: ScrollVideoProps) {
  const sectionRef = React.useRef<HTMLElement>(null);
  const videoRef = React.useRef<HTMLVideoElement>(null);
  const targetTimeRef = React.useRef(0);
  const rafRef = React.useRef<number | null>(null);
  const reducedMotion = usePrefersReducedMotion();
  const isMobile = useMobileMediaQuery();
  const [progress, setProgress] = React.useState(0);
  const [ready, setReady] = React.useState(false);

  const activeSrc = isMobile && mobileSrc ? mobileSrc : src;
  const activePoster = isMobile && mobilePoster ? mobilePoster : poster;
  const activeChapter =
    chapters.find((chapter) => progress >= chapter.start && progress < chapter.end) ??
    chapters[chapters.length - 1];

  const updateProgress = React.useCallback(() => {
    const section = sectionRef.current;
    const video = videoRef.current;
    if (!section) return;

    const rect = section.getBoundingClientRect();
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
    const travel = Math.max(1, rect.height - viewportHeight);
    const nextProgress = clamp(-rect.top / travel);

    setProgress(nextProgress);
    if (video?.duration) {
      targetTimeRef.current = nextProgress * video.duration;
    }
  }, []);

  React.useEffect(() => {
    updateProgress();
    window.addEventListener("scroll", updateProgress, true);
    window.addEventListener("resize", updateProgress);

    const observer =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(updateProgress)
        : null;
    if (sectionRef.current) observer?.observe(sectionRef.current);

    return () => {
      window.removeEventListener("scroll", updateProgress, true);
      window.removeEventListener("resize", updateProgress);
      observer?.disconnect();
    };
  }, [updateProgress]);

  React.useEffect(() => {
    if (reducedMotion) return;

    const tick = () => {
      const video = videoRef.current;
      if (video?.duration) {
        const current = video.currentTime;
        const target = targetTimeRef.current;
        if (Math.abs(target - current) > 0.01) {
          try {
            video.currentTime = current + (target - current) * 0.16;
          } catch {
            // Some browsers reject seeks while metadata is still settling.
          }
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [reducedMotion]);

  if (reducedMotion && fallback) {
    return <>{fallback}</>;
  }

  if (reducedMotion) {
    const chapter = chapters[0];
    return (
      <section className={cn("relative min-h-screen overflow-hidden", className)} {...props}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={activePoster}
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
          style={{ filter: `brightness(${Math.max(0, 100 - darken) / 100})` }}
        />
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/10 to-black/30" />
        <div className="relative z-10 mx-auto flex min-h-screen max-w-7xl items-center px-4 py-24 sm:px-6">
          {chapter && (
            <div className="max-w-3xl space-y-5">
              {chapter.eyebrow && (
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-white/65">
                  {chapter.eyebrow}
                </div>
              )}
              <h2 className="text-balance text-3xl font-semibold leading-tight tracking-normal text-white sm:text-5xl lg:text-6xl">
                {chapter.title}
              </h2>
              {chapter.body && (
                <p className="max-w-2xl text-base leading-relaxed text-white/76 sm:text-lg">
                  {chapter.body}
                </p>
              )}
            </div>
          )}
        </div>
      </section>
    );
  }

  return (
    <section
      ref={sectionRef}
      className={cn("relative", className)}
      style={{ height: `${heightVh}vh` }}
      {...props}
    >
      <div className={cn("sticky top-0 overflow-hidden", minHeightClass)}>
        <video
          key={activeSrc}
          ref={videoRef}
          src={activeSrc}
          poster={activePoster}
          muted
          playsInline
          preload="auto"
          aria-label={videoLabel}
          onLoadedMetadata={() => {
            setReady(true);
            updateProgress();
          }}
          className="absolute inset-0 h-full w-full object-cover"
          style={{
            filter: `brightness(${Math.max(0, 100 - darken) / 100})`,
          }}
        />
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/10 to-black/30" />
        {progressBar && (
          <div className="absolute left-0 top-0 z-20 h-1 bg-white/90" style={{ width: `${progress * 100}%` }} />
        )}
        <div className="relative z-10 mx-auto flex min-h-screen max-w-7xl items-center px-4 py-24 sm:px-6">
          {activeChapter && (
            <div key={`${activeChapter.start}-${activeChapter.end}`} className="max-w-3xl space-y-5">
              {activeChapter.eyebrow && (
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-white/65">
                  {activeChapter.eyebrow}
                </div>
              )}
              <h2 className="text-balance text-3xl font-semibold leading-tight tracking-normal text-white sm:text-5xl lg:text-6xl">
                {activeChapter.title}
              </h2>
              {activeChapter.body && (
                <p className="max-w-2xl text-base leading-relaxed text-white/76 sm:text-lg">
                  {activeChapter.body}
                </p>
              )}
            </div>
          )}
        </div>
        {!ready && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-black text-sm text-white/55">
            Loading video
          </div>
        )}
      </div>
    </section>
  );
}
