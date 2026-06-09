"use client";

import * as React from "react";
import { Play } from "lucide-react";
import { cn } from "@/lib/utils";

type FullBleedVideoHeroProps = Omit<React.HTMLAttributes<HTMLElement>, "title"> & {
  src: string;
  poster: string;
  mobileSrc?: string;
  mobilePoster?: string;
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  align?: "left" | "center" | "right";
  contentWidth?: "md" | "lg" | "xl";
  minHeightClass?: string;
  darken?: number;
  blur?: number;
  videoLabel?: string;
};

const CONTENT_WIDTH = {
  md: "max-w-2xl",
  lg: "max-w-3xl",
  xl: "max-w-5xl",
} satisfies Record<NonNullable<FullBleedVideoHeroProps["contentWidth"]>, string>;

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

export function FullBleedVideoHero({
  src,
  poster,
  mobileSrc,
  mobilePoster,
  eyebrow,
  title,
  description,
  actions,
  align = "left",
  contentWidth = "lg",
  minHeightClass = "min-h-[88vh]",
  darken = 50,
  blur = 0,
  videoLabel = "Hero video",
  className,
  ...props
}: FullBleedVideoHeroProps) {
  const videoRef = React.useRef<HTMLVideoElement>(null);
  const [needsTap, setNeedsTap] = React.useState(false);
  const isMobile = useMobileMediaQuery();
  const reducedMotion = usePrefersReducedMotion();
  const activeSrc = isMobile && mobileSrc ? mobileSrc : src;
  const activePoster = isMobile && mobilePoster ? mobilePoster : poster;

  React.useEffect(() => {
    if (reducedMotion) return;
    const video = videoRef.current;
    if (!video) return;

    setNeedsTap(false);
    const tryPlay = () => {
      const promise = video.play();
      if (promise && typeof promise.catch === "function") {
        promise.catch(() => setNeedsTap(true));
      }
    };

    if (video.readyState >= 2) {
      tryPlay();
      return;
    }

    video.addEventListener("loadeddata", tryPlay, { once: true });
    return () => video.removeEventListener("loadeddata", tryPlay);
  }, [activeSrc, reducedMotion]);

  const onUserPlay = () => {
    videoRef.current
      ?.play()
      .then(() => setNeedsTap(false))
      .catch(() => {
        setNeedsTap(true);
      });
  };

  const textAlign =
    align === "center"
      ? "items-center text-center mx-auto"
      : align === "right"
        ? "items-end text-right ml-auto"
        : "items-start text-left";

  return (
    <section
      className={cn("relative isolate overflow-hidden", minHeightClass, className)}
      {...props}
    >
      <video
        key={activeSrc}
        ref={videoRef}
        src={activeSrc}
        poster={activePoster}
        autoPlay={!reducedMotion}
        loop={!reducedMotion}
        muted
        playsInline
        preload="metadata"
        aria-label={videoLabel}
        className="absolute inset-0 -z-20 h-full w-full object-cover"
        style={{
          filter: `brightness(${Math.max(0, 100 - darken) / 100})${
            blur > 0 ? ` blur(${blur}px)` : ""
          }`,
        }}
      />
      <div className="absolute inset-0 -z-10 bg-gradient-to-t from-black/55 via-black/15 to-black/25" />
      <div className="mx-auto flex min-h-[inherit] max-w-7xl items-center px-4 py-24 sm:px-6 sm:py-28 lg:py-36">
        <div className={cn("flex flex-col gap-6", CONTENT_WIDTH[contentWidth], textAlign)}>
          {eyebrow && (
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-white/70">
              {eyebrow}
            </div>
          )}
          <h1 className="text-balance text-4xl font-semibold leading-tight tracking-normal text-white sm:text-5xl lg:text-7xl">
            {title}
          </h1>
          {description && (
            <p className="max-w-2xl text-base leading-relaxed text-white/78 sm:text-lg">
              {description}
            </p>
          )}
          {actions && (
            <div
              className={cn(
                "flex flex-wrap gap-3 pt-2",
                align === "center" && "justify-center",
                align === "right" && "justify-end",
              )}
            >
              {actions}
            </div>
          )}
        </div>
      </div>
      {needsTap && (
        <button
          type="button"
          onClick={onUserPlay}
          className="absolute inset-0 z-10 flex items-center justify-center bg-black/20 transition-colors hover:bg-black/30"
          aria-label="Play hero video"
        >
          <span className="flex h-16 w-16 items-center justify-center rounded-full bg-white/90 text-black shadow-xl">
            <Play className="ml-1 h-7 w-7" fill="currentColor" />
          </span>
        </button>
      )}
    </section>
  );
}
