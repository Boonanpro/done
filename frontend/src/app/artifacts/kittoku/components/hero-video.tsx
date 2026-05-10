"use client";

import * as React from "react";
import { Play } from "lucide-react";

type Props = {
  src: string;
  poster: string;
  /** スマホ専用に位置調整済みの動画 (省略時は src を共用) */
  mobileSrc?: string;
  mobilePoster?: string;
};

export function HeroVideo({ src, poster, mobileSrc, mobilePoster }: Props) {
  const ref = React.useRef<HTMLVideoElement>(null);
  const [needsTap, setNeedsTap] = React.useState(false);
  // SSR 時は PC 版を出して、クライアントマウント後にスマホかを判定
  const [isMobile, setIsMobile] = React.useState<boolean | null>(null);

  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(max-width: 639px)");
    const update = () => setIsMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  const useMobile = isMobile === true && !!mobileSrc;
  const activeSrc = useMobile ? mobileSrc! : src;
  const activePoster = useMobile && mobilePoster ? mobilePoster : poster;

  // 動画ソース変更時に再生を再キック
  React.useEffect(() => {
    const v = ref.current;
    if (!v) return;
    setNeedsTap(false);
    const tryPlay = () => {
      const p = v.play();
      if (p && typeof p.catch === "function") {
        p.catch(() => setNeedsTap(true));
      }
    };
    if (v.readyState >= 2) {
      tryPlay();
    } else {
      const onLoad = () => tryPlay();
      v.addEventListener("loadeddata", onLoad, { once: true });
      return () => v.removeEventListener("loadeddata", onLoad);
    }
  }, [activeSrc]);

  const onUserPlay = () => {
    const v = ref.current;
    if (!v) return;
    v.play()
      .then(() => setNeedsTap(false))
      .catch(() => {
        /* ignore */
      });
  };

  return (
    <>
      <video
        // key を src に紐付けて、source 切替時に video 要素を再生成
        key={activeSrc}
        ref={ref}
        className="absolute inset-0 w-full h-full object-cover"
        style={{
          filter: "brightness(0.5) saturate(1.05)",
          objectPosition: "center",
        }}
        src={activeSrc}
        poster={activePoster}
        autoPlay
        loop
        muted
        playsInline
        preload="auto"
        aria-label="吉川特装 紹介動画"
      />
      {needsTap && (
        <button
          type="button"
          onClick={onUserPlay}
          className="absolute inset-0 flex items-center justify-center bg-black/20 hover:bg-black/30 transition-colors"
          aria-label="動画を再生"
        >
          <span className="h-16 w-16 rounded-full bg-white/90 text-[var(--yk-navy)] flex items-center justify-center shadow-lg">
            <Play className="h-7 w-7 ml-1" fill="currentColor" />
          </span>
        </button>
      )}
    </>
  );
}
